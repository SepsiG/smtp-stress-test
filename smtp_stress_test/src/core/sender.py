import asyncio
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Union
import ssl
import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

from .scenario import TestScenario

class ErrorCategory:
    AUTH = "Authentication Error"
    CONNECTION = "Connection Error"
    SMTP = "SMTP Protocol Error"
    TLS = "TLS Error"
    RATE_LIMIT = "Rate Limit Error"
    RECIPIENT = "Recipient Error"
    OTHER = "Other Error"

    @staticmethod
    def categorize_error(error: Exception) -> tuple[str, Optional[str]]:
        """Categorize the error and extract SMTP response code if available"""
        smtp_code = None
        
        if isinstance(error, aiosmtplib.SMTPAuthenticationError):
            return ErrorCategory.AUTH, str(error.code)
        elif isinstance(error, (aiosmtplib.SMTPConnectError, aiosmtplib.SMTPTimeoutError)):
            return ErrorCategory.CONNECTION, None
        elif isinstance(error, (aiosmtplib.SMTPRecipientRefused, aiosmtplib.SMTPRecipientsRefused)):
            return ErrorCategory.RECIPIENT, str(getattr(error, 'code', None))
        elif isinstance(error, aiosmtplib.SMTPSenderRefused):
            return ErrorCategory.SMTP, str(error.code)
        elif isinstance(error, ssl.SSLError):
            return ErrorCategory.TLS, None
        elif isinstance(error, aiosmtplib.SMTPResponseException):
            code = str(error.code)
            if code.startswith('421') or code.startswith('451') or code.startswith('554'):
                return ErrorCategory.RATE_LIMIT, code
            elif code.startswith('550') or code.startswith('553'):
                return ErrorCategory.RECIPIENT, code
            return ErrorCategory.SMTP, code
        
        return ErrorCategory.OTHER, None

class SMTPSender:
    def __init__(self, scenario: TestScenario):
        self.scenario = scenario
        self.results: List[Dict[str, Any]] = []
        self.logger = self._setup_logger()
        self._running_tasks: List[asyncio.Task] = []
        # Alapértelmezett timeout beállítások
        self.timeout_settings = {
            "connect_timeout": 1.0,
            "send_timeout": 1.0
        }
        # Próbáljuk meg lekérni a globális beállításokat az API-ból
        asyncio.create_task(self._load_timeout_settings())

    def _setup_logger(self) -> logging.Logger:
        logger = logging.getLogger(f"smtp_test_{self.scenario.name}")
        logger.setLevel(logging.INFO)
        
        log_path = Path("logs") / f"{self.scenario.name}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        file_handler = logging.FileHandler(log_path)
        file_handler.setLevel(logging.INFO)
        
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
        
        return logger

    async def send_email(self, email_index: int, recipients: List[str]) -> Dict[str, Any]:
        msg = MIMEMultipart()
        msg['From'] = self.scenario.email_template.from_email
        msg['To'] = ', '.join(recipients)
        msg['Subject'] = self.scenario.email_template.subject
        
        if self.scenario.email_template.cc_email:
            msg['Cc'] = ', '.join(self.scenario.email_template.cc_email)
        if self.scenario.email_template.bcc_email:
            msg['Bcc'] = ', '.join(self.scenario.email_template.bcc_email)

        msg.attach(MIMEText(self.scenario.email_template.body, 'plain'))

        if self.scenario.email_template.attachments:
            for attachment_path in self.scenario.email_template.attachments:
                with open(attachment_path, 'rb') as f:
                    part = MIMEApplication(f.read(), Name=attachment_path.name)
                part['Content-Disposition'] = f'attachment; filename="{attachment_path.name}"'
                msg.attach(part)

        start_time = datetime.now()
        result = {
            'email_index': email_index,
            'start_time': start_time.isoformat(),
            'status': 'failed',
            'error': None,
            'error_category': None,
            'smtp_code': None,
            'to': msg['To'],
            'recipient_count': len(recipients)
        }

        try:
            # Create SSL context and set certificate verification based on scenario config
            ssl_context = ssl.create_default_context()
            if not self.scenario.smtp_config.verify_cert:
                # Disable certificate verification if specified in the scenario
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE
                self.logger.info("TLS/SSL certificate verification disabled for this scenario")

            smtp = aiosmtplib.SMTP(
                hostname=self.scenario.smtp_config.host,
                port=self.scenario.smtp_config.port,
                use_tls=self.scenario.smtp_config.use_tls,
                tls_context=ssl_context,
                source_address=('0.0.0.0', 0),  # Dinamikus forrás port használata
                local_hostname='smtptester.local',  # Fix hostname beállítása
                timeout=self.timeout_settings["connect_timeout"]  # Dinamikus timeout beállítás
            )
            
            # Timeout paraméter a gyorsabb kapcsolódásért
            await smtp.connect(timeout=self.timeout_settings["connect_timeout"])
            
            if self.scenario.smtp_config.username and self.scenario.smtp_config.password:
                await smtp.login(
                    self.scenario.smtp_config.username,
                    self.scenario.smtp_config.password,
                    timeout=self.timeout_settings["send_timeout"]
                )

            await smtp.send_message(msg, timeout=self.timeout_settings["send_timeout"])
            await smtp.quit(timeout=self.timeout_settings["send_timeout"])
            
            result['status'] = 'success'
            self.logger.info(f"Email {email_index} sent successfully to {msg['To']}")
            
        except Exception as e:
            error_category, smtp_code = ErrorCategory.categorize_error(e)
            error_msg = str(e)
            
            result.update({
                'error': error_msg,
                'error_category': error_category,
                'smtp_code': smtp_code
            })
            
            self.logger.error(
                f"Failed to send email {email_index} to {msg['To']}: "
                f"[{error_category}] {error_msg}"
                + (f" (SMTP code: {smtp_code})" if smtp_code else "")
            )
            
        finally:
            end_time = datetime.now()
            result['end_time'] = end_time.isoformat()
            result['duration'] = (end_time - start_time).total_seconds()
            return result

    def _distribute_recipients(self) -> List[List[str]]:
        """Distribute recipients across threads and emails evenly"""
        all_recipients = self.scenario.email_template.to_email
        total_emails = self.scenario.num_threads * self.scenario.emails_per_thread
        
        # If we have fewer emails than recipients, we'll need to batch recipients together
        if len(all_recipients) > total_emails:
            # Calculate how many recipients per email
            recipients_per_email = (len(all_recipients) + total_emails - 1) // total_emails
            distributed_recipients = []
            
            for i in range(0, len(all_recipients), recipients_per_email):
                batch = all_recipients[i:i + recipients_per_email]
                distributed_recipients.append(batch)
                if len(distributed_recipients) >= total_emails:
                    break
                    
        # If we have more emails than recipients, we'll cycle through the recipients
        else:
            cycles_needed = (total_emails + len(all_recipients) - 1) // len(all_recipients)
            repeated_recipients = all_recipients * cycles_needed
            distributed_recipients = [[recipient] for recipient in repeated_recipients[:total_emails]]
                
        return distributed_recipients

    async def run_thread(self, thread_id: int) -> List[Dict[str, Any]]:
        thread_results = []
        all_recipients = self._distribute_recipients()
        
        try:
            # Számold ki a szálon belül küldendő e-mailek mennyiségét
            emails_per_thread = self.scenario.emails_per_thread
            
            for email_index in range(emails_per_thread):
                # Számold ki, mely címzettek tartoznak ehhez az e-mailhez
                overall_index = thread_id * emails_per_thread + email_index
                recipients = all_recipients[overall_index % len(all_recipients)] if overall_index < len(all_recipients) else all_recipients[0]
                
                try:
                    result = await self.send_email(email_index, recipients)
                    thread_results.append(result)
                    await asyncio.sleep(self.scenario.delay_between_emails)
                except asyncio.CancelledError:
                    self.logger.info(f"Thread {thread_id} cancelled during email sending")
                    raise
                except Exception as e:
                    self.logger.error(f"Error in thread {thread_id}: {str(e)}")
                    thread_results.append({
                        "thread_id": thread_id,
                        "email_index": email_index,
                        "status": "error",
                        "error": str(e),
                        "timestamp": datetime.now().isoformat()
                    })
        except asyncio.CancelledError:
            self.logger.info(f"Thread {thread_id} cancelled")
            raise
            
        return thread_results

    async def run_test(self) -> List[Dict[str, Any]]:
        try:
            threads = []
            for thread_id in range(self.scenario.num_threads):
                task = asyncio.create_task(self.run_thread(thread_id))
                self._running_tasks.append(task)
                threads.append(task)
            
            try:
                # Wait for all threads to complete
                results = await asyncio.gather(*threads)
                # Flatten results from all threads
                self.results = [item for sublist in results for item in sublist]
                return self.results
            except asyncio.CancelledError:
                # Cancel all running tasks
                for task in self._running_tasks:
                    if not task.done():
                        task.cancel()
                # Wait for tasks to finish cancelling
                await asyncio.gather(*self._running_tasks, return_exceptions=True)
                self.logger.info("Test execution cancelled")
                raise
            finally:
                self._running_tasks.clear()
        except Exception as e:
            self.logger.error(f"Error during test execution: {str(e)}")
            raise

    async def _load_timeout_settings(self):
        """Timeout beállítások lekérése az API-ból"""
        try:
            # Mivel közvetlenül nem tudunk HTTP kérést indítani a belső API-hoz a modell miatt,
            # itt feltételezzük, hogy a globális timeout_settings változók már be vannak állítva
            # az app.py-ban, és azokat fogjuk használni
            from ..api.app import timeout_settings
            self.timeout_settings = timeout_settings.copy()
            self.logger.info(f"Timeout beállítások betöltve: {self.timeout_settings}")
        except Exception as e:
            self.logger.warning(f"Nem sikerült betölteni a timeout beállításokat: {str(e)}, alapértelmezett értékek használata")
            # Alapértelmezett értékek használata, ha hiba történik
            self.timeout_settings = {
                "connect_timeout": 1.0,
                "send_timeout": 1.0
            }
