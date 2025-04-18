import uvicorn
import os
import sys
import threading
import time
import webbrowser

# Add the project root to the Python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def open_browser():
    """Várakozik 1.5 másodpercet, hogy a szerver elinduljon, majd megnyitja a böngészőt"""
    time.sleep(1.5)
    webbrowser.open("http://localhost:8000")


if __name__ == "__main__":
    # Indíts egy háttérszálat a böngésző megnyitásához
    threading.Thread(target=open_browser).start()
    
    # Indítsd el a szervert
    uvicorn.run("smtp_stress_test.src.api.app:app", host="0.0.0.0", port=8000, reload=True)
