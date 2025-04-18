from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Request, Body
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from pathlib import Path
import asyncio
import json
from typing import List, Dict, Any, Optional
import aiofiles
from datetime import datetime

from ..core import TestScenario, SMTPSender, TestReporter, ScenarioMetadata

# Get the absolute path to the project root and template directories
BASE_DIR = Path(__file__).resolve().parent.parent.parent
TEMPLATE_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"
SCENARIOS_DIR = BASE_DIR / "scenarios"
REPORTS_DIR = BASE_DIR / "reports"  # This is inside smtp_stress_test/reports

# Create necessary directories
TEMPLATE_DIR.mkdir(exist_ok=True)
STATIC_DIR.mkdir(exist_ok=True)
SCENARIOS_DIR.mkdir(exist_ok=True)
REPORTS_DIR.mkdir(exist_ok=True)

# Define logs directory
LOGS_DIR = Path("logs")
LOGS_DIR.mkdir(exist_ok=True)

# Create FastAPI app
app = FastAPI(title="SMTP Stress Test")

# Mount static files and templates
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATE_DIR))

@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse(
        name="index.html",
        context={"request": request}
    )

# Globális timeout beállítások
timeout_settings = {
    "connect_timeout": 1.0,
    "send_timeout": 1.0
}

# Store running tests
active_tests: Dict[str, asyncio.Task] = {}

async def run_test_scenario(scenario: TestScenario) -> None:
    try:
        # Update scenario metadata before running test
        metadata = ScenarioMetadata(scenario.name)
        metadata.update_run()
        
        sender = SMTPSender(scenario)
        try:
            results = await sender.run_test()
            
            # Generate reports only if test wasn't cancelled
            reporter = TestReporter(scenario.name, results)
            try:
                json_report = reporter.save_json_report(REPORTS_DIR)
                html_report = reporter.generate_html_report(TEMPLATE_DIR, REPORTS_DIR)
                print(f"Reports generated successfully: JSON={json_report}, HTML={html_report}")
            except Exception as report_error:
                print(f"Error generating reports: {str(report_error)}")
                raise Exception(f"Test completed but report generation failed: {str(report_error)}")
        except asyncio.CancelledError:
            print(f"Test cancelled for scenario: {scenario.name}")
            raise
            
    except Exception as e:
        print(f"Error in run_test_scenario: {str(e)}")
        raise e
    finally:
        if scenario.name in active_tests:
            del active_tests[scenario.name]

@app.post("/scenarios/upload")
async def upload_scenario(file: UploadFile = File(...)):
    if not file.filename.endswith('.json'):
        raise HTTPException(status_code=400, detail="Only JSON files are allowed")
    
    content = await file.read()
    scenario_data = json.loads(content)
    
    # Save scenario to scenarios directory
    scenario_path = SCENARIOS_DIR / file.filename
    async with aiofiles.open(scenario_path, 'wb') as f:
        await f.write(content)
    
    return {"message": "Scenario uploaded successfully"}

@app.post("/scenarios/create")
async def create_scenario(scenario_data: dict = Body(...)):
    if not scenario_data.get("name"):
        raise HTTPException(status_code=400, detail="Name is required")
    
    scenario_path = SCENARIOS_DIR / f"{scenario_data['name']}.json"
    if scenario_path.exists():
        raise HTTPException(status_code=400, detail="Scenario with this name already exists")
    
    async with aiofiles.open(scenario_path, 'w') as f:
        await f.write(json.dumps(scenario_data, indent=4))
    
    # Initialize metadata for new scenario
    ScenarioMetadata(scenario_data['name'])
    
    return {"message": "Scenario created successfully"}

@app.put("/scenarios/{scenario_name}")
async def update_scenario(scenario_name: str, scenario_data: dict = Body(...)):
    scenario_path = SCENARIOS_DIR / f"{scenario_name}.json"
    if not scenario_path.exists():
        raise HTTPException(status_code=404, detail="Scenario not found")
    
    async with aiofiles.open(scenario_path, 'w') as f:
        await f.write(json.dumps(scenario_data, indent=4))
    
    return {"message": "Scenario updated successfully"}

@app.delete("/scenarios/{scenario_name}")
async def delete_scenario(scenario_name: str):
    scenario_path = SCENARIOS_DIR / f"{scenario_name}.json"
    if not scenario_path.exists():
        raise HTTPException(status_code=404, detail="Scenario not found")
    
    # Read scenario data to get attachment paths
    async with aiofiles.open(scenario_path, 'r') as f:
        content = await f.read()
        scenario_data = json.loads(content)
        
    # Delete attachments if they exist
    if 'email_template' in scenario_data and 'attachments' in scenario_data['email_template']:
        for attachment_path in scenario_data['email_template']['attachments']:
            try:
                Path(attachment_path).unlink(missing_ok=True)
            except Exception as e:
                print(f"Failed to delete attachment {attachment_path}: {e}")
    
    # Delete metadata file if exists
    metadata_path = SCENARIOS_DIR / "metadata" / f"{scenario_name}.metadata.json"
    if metadata_path.exists():
        try:
            metadata_path.unlink()
            print(f"Deleted metadata file for scenario: {scenario_name}")
        except Exception as e:
            print(f"Failed to delete metadata file for {scenario_name}: {e}")
    
    scenario_path.unlink()
    return {"message": "Scenario deleted successfully"}

@app.get("/scenarios/{scenario_name}")
async def get_scenario(scenario_name: str):
    scenario_path = SCENARIOS_DIR / f"{scenario_name}.json"
    if not scenario_path.exists():
        raise HTTPException(status_code=404, detail="Scenario not found")
    
    async with aiofiles.open(scenario_path, 'r') as f:
        content = await f.read()
        return JSONResponse(content=json.loads(content))

@app.get("/scenarios")
async def list_scenarios():
    scenarios = []
    
    for scenario_file in SCENARIOS_DIR.glob("*.json"):
        with open(scenario_file) as f:
            scenario_data = json.load(f)
            metadata = ScenarioMetadata(scenario_data["name"])
            scenarios.append({
                "name": scenario_data["name"],
                "description": scenario_data["description"],
                "filename": scenario_file.name,
                "metadata": metadata.to_dict()
            })
    
    return scenarios

@app.post("/tests/start/{scenario_name}")
async def start_test(scenario_name: str, background_tasks: BackgroundTasks):
    scenario_path = SCENARIOS_DIR / f"{scenario_name}.json"
    
    if not scenario_path.exists():
        raise HTTPException(status_code=404, detail="Scenario not found")
    
    try:
        scenario = TestScenario.from_json(scenario_path)
        task = asyncio.create_task(run_test_scenario(scenario))
        active_tests[scenario.name] = task
        
        return {"message": f"Test started for scenario: {scenario_name}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/tests/stop/{scenario_name}")
async def stop_test(scenario_name: str):
    if scenario_name in active_tests:
        task = active_tests[scenario_name]
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        del active_tests[scenario_name]
        return {"message": f"Test stopped for scenario: {scenario_name}"}
    raise HTTPException(status_code=404, detail="No running test found for this scenario")

@app.post("/scenarios/stop")
async def stop_scenarios():
    """Stop all running test scenarios"""
    for test_id, task in active_tests.items():
        if not task.done():
            task.cancel()
    active_tests.clear()
    return {"message": "All running tests have been stopped"}

@app.get("/tests/status/{scenario_name}")
async def get_test_status(scenario_name: str):
    # Check if the test is currently running
    if scenario_name in active_tests:
        task = active_tests[scenario_name]
        if task.done():
            if task.exception():
                error = str(task.exception())
                del active_tests[scenario_name]
                return {"status": "error", "error": error}
            
            del active_tests[scenario_name]
            
            # Check if there's a report
            report_pattern = f"report_{scenario_name}_*.json"
            reports = list(REPORTS_DIR.glob(report_pattern))
            if reports:
                # Get the latest report
                latest_report = sorted(reports, key=lambda x: x.stat().st_mtime, reverse=True)[0]
                return {
                    "status": "completed",
                    "report": {
                        "name": scenario_name,
                        "html": f"/reports/{latest_report.stem}.html",
                        "json": f"/reports/{latest_report.stem}.json"
                    }
                }
            return {"status": "completed", "error": "Report not found"}
        return {"status": "running"}
    
    # Check if there's a report for a completed test
    report_pattern = f"report_{scenario_name}_*.json"
    reports = list(REPORTS_DIR.glob(report_pattern))
    if reports:
        # Get the latest report
        latest_report = sorted(reports, key=lambda x: x.stat().st_mtime, reverse=True)[0]
        return {
            "status": "completed",
            "report": {
                "name": scenario_name,
                "html": f"/reports/{latest_report.stem}.html",
                "json": f"/reports/{latest_report.stem}.json"
            }
        }
    
    return {"status": "not_found"}

@app.get("/reports")
async def list_reports():
    reports = []
    try:
        for report_file in REPORTS_DIR.glob("report_*.html"):
            # Extract the scenario name from the report filename
            name_parts = report_file.stem.split('_')
            if len(name_parts) >= 3:  # ["report", "scenario_name", "timestamp"]
                scenario_name = '_'.join(name_parts[1:-1])
            else:
                scenario_name = report_file.stem
                
            # Check if corresponding JSON exists
            json_file = report_file.with_suffix('.json')
            if json_file.exists():
                try:
                    with open(json_file, 'r') as f:
                        report_data = json.load(f)
                        success_rate = report_data.get('statistics', {}).get('success_rate', 0)
                except Exception as e:
                    print(f"Error reading JSON report {json_file}: {e}")
                    success_rate = None
            else:
                success_rate = None
                
            reports.append({
                "name": scenario_name,
                "filename": report_file.name,
                "html_url": f"/reports/{report_file.name}",
                "json_url": f"/reports/{report_file.stem}.json",
                "created": report_file.stat().st_mtime,
                "success_rate": success_rate
            })
    except Exception as e:
        print(f"Error listing reports: {e}")
        
    return sorted(reports, key=lambda x: x["created"], reverse=True)

@app.get("/reports/{report_name}")
async def get_report(report_name: str):
    # First try with the exact name
    report_path = REPORTS_DIR / report_name
    
    # If not found, try appending extensions
    if not report_path.exists():
        if report_name.endswith('.html'):
            report_path = REPORTS_DIR / report_name
        elif report_name.endswith('.json'):
            report_path = REPORTS_DIR / report_name
        else:
            # Try to find any report file matching this name
            html_path = REPORTS_DIR / f"{report_name}.html"
            json_path = REPORTS_DIR / f"{report_name}.json"
            if html_path.exists():
                report_path = html_path
            elif json_path.exists():
                report_path = json_path
    
    if not report_path.exists():
        raise HTTPException(status_code=404, detail="Report not found")
    
    return FileResponse(report_path)

@app.delete("/reports")
async def delete_all_reports():
    try:
        # Delete all HTML and JSON report files
        for report_file in REPORTS_DIR.glob("report_*"):
            report_file.unlink()
        return {"message": "Az összes riport sikeresen törölve"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Hiba történt a riportok törlése során: {str(e)}")

@app.post("/scenarios/upload-attachments")
async def upload_attachments(files: List[UploadFile] = File(...)):
    attachment_paths = []
    attachment_dir = SCENARIOS_DIR / "attachments"
    attachment_dir.mkdir(exist_ok=True)
    
    for file in files:
        # Generate a unique filename to avoid conflicts
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_filename = f"{timestamp}_{file.filename}"
        file_path = attachment_dir / safe_filename
        
        content = await file.read()
        async with aiofiles.open(file_path, 'wb') as f:
            await f.write(content)
        
        attachment_paths.append(str(file_path))
    
    return {"paths": attachment_paths}

@app.delete("/scenarios")
async def delete_all_scenarios():
    try:
        # Delete all scenario files and their metadata
        for scenario_file in SCENARIOS_DIR.glob("*.json"):
            scenario_name = scenario_file.stem
            # Read scenario data to get attachment paths
            async with aiofiles.open(scenario_file, 'r') as f:
                content = await f.read()
                scenario_data = json.loads(content)
                
            # Delete attachments if they exist
            if 'email_template' in scenario_data and 'attachments' in scenario_data['email_template']:
                for attachment_path in scenario_data['email_template']['attachments']:
                    try:
                        Path(attachment_path).unlink(missing_ok=True)
                    except Exception as e:
                        print(f"Failed to delete attachment {attachment_path}: {e}")
            
            # Delete metadata file if exists
            metadata_path = SCENARIOS_DIR / "metadata" / f"{scenario_name}.metadata.json"
            if metadata_path.exists():
                metadata_path.unlink()
            
            # Delete the scenario file
            scenario_file.unlink()
            
        return {"message": "Az összes scenario sikeresen törölve"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Hiba történt a scenariók törlése során: {str(e)}")

@app.get("/logs")
async def list_logs():
    """Visszaadja az összes elérhető log fájlt"""
    logs = []
    try:
        for log_file in LOGS_DIR.glob("*.log"):
            scenario_name = log_file.stem.split('_')[0] if '_' in log_file.stem else log_file.stem
            logs.append({
                "name": scenario_name,
                "filename": log_file.name,
                "path": f"/logs/{log_file.name}",
                "created": log_file.stat().st_mtime,
                "size": log_file.stat().st_size
            })
    except Exception as e:
        print(f"Error listing logs: {e}")
        
    return sorted(logs, key=lambda x: x["created"], reverse=True)

@app.get("/logs/{log_filename}")
async def get_log_content(log_filename: str):
    """Visszaadja egy log fájl tartalmát"""
    log_path = LOGS_DIR / log_filename
    
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="Log file not found")
    
    try:
        async with aiofiles.open(log_path, 'r') as f:
            content = await f.read()
        return {"filename": log_filename, "content": content}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading log file: {str(e)}")

@app.delete("/logs/{log_filename}")
async def delete_log(log_filename: str):
    """Töröl egy log fájlt"""
    log_path = LOGS_DIR / log_filename
    
    if not log_path.exists():
        raise HTTPException(status_code=404, detail="Log file not found")
    
    try:
        log_path.unlink()
        return {"message": f"Log file {log_filename} has been deleted"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting log file: {str(e)}")

@app.delete("/logs")
async def delete_all_logs():
    """Töröl minden log fájlt"""
    try:
        deleted_count = 0
        for log_file in LOGS_DIR.glob("*.log"):
            log_file.unlink()
            deleted_count += 1
        return {"message": f"All log files have been deleted ({deleted_count} files)"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error deleting log files: {str(e)}")

# Mount reports directory for static file access - must be after all API routes
app.mount("/reports", StaticFiles(directory=str(REPORTS_DIR)), name="reports")
app.mount("/logs", StaticFiles(directory=str(LOGS_DIR)), name="logs")

@app.post("/settings/timeout")
async def update_timeout_settings(settings: dict = Body(...)):
    """Timeout beállítások frissítése"""
    global timeout_settings
    
    if "connect_timeout" in settings:
        timeout_settings["connect_timeout"] = float(settings["connect_timeout"])
    
    if "send_timeout" in settings:
        timeout_settings["send_timeout"] = float(settings["send_timeout"])
    
    return {"message": "Timeout beállítások sikeresen frissítve", "settings": timeout_settings}

@app.get("/settings/timeout")
async def get_timeout_settings():
    """Jelenlegi timeout beállítások lekérése"""
    return timeout_settings
