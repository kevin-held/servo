import os
import sys
from pathlib import Path

# Add project root to path
sys.path.append(str(Path(__file__).parent.parent))

from gui.startup_worker import StartupWorker
from PySide6.QtCore import QCoreApplication

def test_startup_worker():
    app = QCoreApplication(sys.argv)
    worker = StartupWorker(run_fast=True, run_deep=False)
    
    def on_finished(report):
        print("\n=== STARTUP REPORT ===")
        print(report)
        print("======================\n")
        app.quit()
        
    worker.finished_report.connect(on_finished)
    worker.start()
    app.exec()

if __name__ == "__main__":
    test_startup_worker()
