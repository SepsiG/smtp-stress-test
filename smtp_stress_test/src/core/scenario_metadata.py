from typing import Dict, Any
from pathlib import Path
import json
from datetime import datetime


class ScenarioMetadata:
    def __init__(self, scenario_name: str):
        self.scenario_name = scenario_name
        self.created_at = None
        self.last_run = None
        self.run_count = 0
        self._load()
    
    def _get_metadata_path(self) -> Path:
        base_dir = Path(__file__).resolve().parent.parent.parent
        metadata_dir = base_dir / "scenarios" / "metadata"
        metadata_dir.mkdir(exist_ok=True)
        return metadata_dir / f"{self.scenario_name}.metadata.json"
    
    def _load(self):
        path = self._get_metadata_path()
        if path.exists():
            with open(path, 'r') as f:
                data = json.load(f)
                self.created_at = data.get('created_at')
                self.last_run = data.get('last_run')
                self.run_count = data.get('run_count', 0)
        else:
            # If metadata doesn't exist, this is a new scenario
            self.created_at = datetime.now().isoformat()
            self.save()
    
    def update_run(self):
        self.last_run = datetime.now().isoformat()
        self.run_count += 1
        self.save()
    
    def save(self):
        path = self._get_metadata_path()
        with open(path, 'w') as f:
            json.dump({
                'scenario_name': self.scenario_name,
                'created_at': self.created_at,
                'last_run': self.last_run,
                'run_count': self.run_count
            }, f, indent=4)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            'created_at': self.created_at,
            'last_run': self.last_run,
            'run_count': self.run_count
        }

__all__ = ['ScenarioMetadata']
