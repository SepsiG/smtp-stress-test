from dataclasses import dataclass
from typing import List, Dict, Optional
from pathlib import Path
import json

@dataclass
class EmailTemplate:
    subject: str
    body: str
    from_email: str
    to_email: List[str]
    cc_email: Optional[List[str]] = None
    bcc_email: Optional[List[str]] = None
    attachments: Optional[List[Path]] = None

@dataclass
class SMTPConfig:
    host: str
    port: int
    use_tls: bool = True
    verify_cert: bool = True
    username: Optional[str] = None
    password: Optional[str] = None

@dataclass
class TestScenario:
    name: str
    description: str
    smtp_config: SMTPConfig
    email_template: EmailTemplate
    num_threads: int
    emails_per_thread: int
    delay_between_emails: float = 0.0

    @classmethod
    def from_json(cls, json_path: Path) -> 'TestScenario':
        with open(json_path, 'r') as f:
            data = json.load(f)
        
        smtp_config = SMTPConfig(**data['smtp_config'])
        email_template = EmailTemplate(**data['email_template'])
        
        return cls(
            name=data['name'],
            description=data['description'],
            smtp_config=smtp_config,
            email_template=email_template,
            num_threads=data['num_threads'],
            emails_per_thread=data['emails_per_thread'],
            delay_between_emails=data.get('delay_between_emails', 0.0)
        )

    def to_json(self, json_path: Path) -> None:
        data = {
            'name': self.name,
            'description': self.description,
            'smtp_config': {
                'host': self.smtp_config.host,
                'port': self.smtp_config.port,
                'use_tls': self.smtp_config.use_tls,
                'username': self.smtp_config.username,
                'password': self.smtp_config.password
            },
            'email_template': {
                'subject': self.email_template.subject,
                'body': self.email_template.body,
                'from_email': self.email_template.from_email,
                'to_email': self.email_template.to_email,
                'cc_email': self.email_template.cc_email,
                'bcc_email': self.email_template.bcc_email,
                'attachments': [str(path) for path in (self.email_template.attachments or [])]
            },
            'num_threads': self.num_threads,
            'emails_per_thread': self.emails_per_thread,
            'delay_between_emails': self.delay_between_emails
        }
        
        with open(json_path, 'w') as f:
            json.dump(data, f, indent=4)
