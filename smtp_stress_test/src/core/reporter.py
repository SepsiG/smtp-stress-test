from typing import Dict, List, Any
from pathlib import Path
import json
from datetime import datetime
import pandas as pd
from jinja2 import Environment, FileSystemLoader

class TestReporter:
    def __init__(self, scenario_name: str, results: List[Dict[str, Any]]):
        self.scenario_name = scenario_name
        self.results = results
        self.report_time = datetime.now()
        
    def generate_statistics(self) -> Dict[str, Any]:
        df = pd.DataFrame(self.results)
        total_emails = len(self.results)
        successful_emails = len(df[df['status'] == 'success'])
        failed_emails = total_emails - successful_emails
        
        # Calculate timing statistics
        df['start_time'] = pd.to_datetime(df['start_time'])
        df['end_time'] = pd.to_datetime(df['end_time'])
        df['duration'] = (df['end_time'] - df['start_time']).dt.total_seconds()
        
        stats = {
            'scenario_name': self.scenario_name,
            'report_time': self.report_time.isoformat(),
            'test_start_time': df['start_time'].min().isoformat(),
            'test_end_time': df['end_time'].max().isoformat(),
            'total_emails': int(total_emails),
            'total_recipients': int(df['recipient_count'].sum()),
            'avg_recipients_per_email': float(df['recipient_count'].mean()),
            'successful_emails': int(successful_emails),
            'failed_emails': int(failed_emails),
            'success_rate': float((successful_emails / total_emails) * 100),
            'avg_duration': float(df['duration'].mean()),
            'min_duration': float(df['duration'].min()),
            'max_duration': float(df['duration'].max()),
            'emails_per_second': float(total_emails / df['duration'].sum())
        }
        
        # Error analysis
        if failed_emails > 0:
            failed_df = df[df['status'] == 'failed']
            # Error categories analysis
            error_categories = failed_df['error_category'].value_counts()
            stats['error_categories'] = {str(k): int(v) for k, v in error_categories.items()}
            
            # SMTP code analysis
            smtp_codes = failed_df[failed_df['smtp_code'].notna()]['smtp_code'].value_counts()
            if not smtp_codes.empty:
                stats['smtp_codes'] = {str(k): int(v) for k, v in smtp_codes.items()}
            else:
                stats['smtp_codes'] = {}
                
            # Error breakdown
            error_counts = failed_df['error'].value_counts()
            stats['error_breakdown'] = {str(k): int(v) for k, v in error_counts.items()}
        else:
            stats['error_categories'] = {}
            stats['smtp_codes'] = {}
            stats['error_breakdown'] = {}
            
        return stats
    
    def save_json_report(self, output_dir: Path) -> Path:
        stats = self.generate_statistics()
        
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        report_file = output_dir / f"report_{self.scenario_name}_{self.report_time.strftime('%Y%m%d_%H%M%S')}.json"
        
        with open(report_file, 'w') as f:
            json.dump({
                'statistics': stats,
                'detailed_results': self.results
            }, f, indent=4)
            
        return report_file
    
    def generate_html_report(self, template_dir: Path, output_dir: Path) -> Path:
        stats = self.generate_statistics()
        
        env = Environment(loader=FileSystemLoader(template_dir))
        template = env.get_template('report_template.html')
        
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        
        report_file = output_dir / f"report_{self.scenario_name}_{self.report_time.strftime('%Y%m%d_%H%M%S')}.html"
        
        html_content = template.render(
            stats=stats,
            results=self.results,
            datetime=datetime
        )
        
        with open(report_file, 'w') as f:
            f.write(html_content)
            
        return report_file
