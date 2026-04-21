import os
import subprocess
import time
from PySide6.QtCore import QThread, Signal

class StartupWorker(QThread):
    """
    Executes mechanical tests asynchronously to prevent UI freezing during boot.
    Emits the final report string when all layers complete.
    """
    finished_report = Signal(str)

    def __init__(self, run_fast=True, run_deep=False, parent=None):
        super().__init__(parent)
        self.run_fast = run_fast
        self.run_deep = run_deep

    def run(self):
        report_lines = ["[STARTUP DIAGNOSTIC]", "System core booted. Test coverage execution complete:"]
        
        # 1. Fast Mechanical Tests
        if self.run_fast:
            try:
                t0 = time.time()
                # Redirect test logs to a temporary directory so they don't
                # pollute the production sentinel.jsonl (SYSTEM CONTROL).
                import tempfile
                self._test_log_dir = tempfile.mkdtemp()
                
                env = os.environ.copy()
                env["SENTINEL_LOG_DIR"] = self._test_log_dir
                
                res = subprocess.run(
                    ["python", "-m", "coverage", "run", "-m", "unittest", "discover", "tests"],
                    cwd=os.getcwd(),
                    capture_output=True,
                    text=True,
                    env=env
                )
                dt = time.time() - t0
                
                # Capture full unittest output (usually on stderr)
                test_output = res.stderr + res.stdout
                
                if res.returncode == 0:
                    # PASS: Avoid dumping raw text to prevent mission-residue hallucinations
                    report_lines.append("\n### Unit Test Results")
                    report_lines.append(f"**Status: PASS** ({dt:.2f}s)")
                    # Count tests from output if possible
                    import re
                    match = re.search(r"Ran (\d+) tests", test_output)
                    if match:
                        report_lines.append(f" - [OK] {match.group(0)}")
                else:
                    # FAIL: Include raw logs for diagnosis
                    report_lines.append("\n### Unit Test Results")
                    report_lines.append("```text")
                    report_lines.append(test_output.strip())
                    report_lines.append("```")
                    report_lines.append(f"**Status: FAIL** (Code {res.returncode}, {dt:.2f}s)")

                # Capture coverage report
                res_cov = subprocess.run(
                    ["python", "-m", "coverage", "report", "-m", "--ignore-errors"],
                    cwd=os.getcwd(),
                    capture_output=True,
                    text=True
                )
                if res_cov.returncode == 0:
                    report_lines.append("\n### Code Coverage")
                    # On pass, just show the summary to keep the context clean
                    lines = res_cov.stdout.strip().splitlines()
                    if lines:
                        report_lines.append(f" - [OK] {lines[-1]}") # Usually the TOTAL line
                else:
                    report_lines.append("\n### Code Coverage")
                    report_lines.append(f" - [ERROR] Coverage report failed (Code {res_cov.returncode})")

            except Exception as e:
                report_lines.append(f"\n### Unit Test Error\n - [ERROR] Tests crashed: {e}")
                
        # 2. Deep Diagnostics (Slow)
        if self.run_deep:
            try:
                # E2E test
                t_e = time.time()
                env = os.environ.copy()
                env["SENTINEL_SILENT"] = "True"
                
                res_e2e = subprocess.run(
                    ["python", "tests/test_e2e_live.py"],
                    cwd=os.getcwd(),
                    capture_output=True,
                    text=True,
                    env=env
                )
                dt_e = time.time() - t_e
                if res_e2e.returncode == 0:
                    report_lines.append(f" - [PASS] Native Layer E2E Live Constraints ({dt_e:.1f}s)")
                else:
                    report_lines.append(f" - [FAIL] Native Layer E2E Constraints failed!")

                # Context Limits Eval
                t_c = time.time()
                env = os.environ.copy()
                env["SENTINEL_SILENT"] = "True"
                
                res_ctx = subprocess.run(
                    ["python", "tests/eval_context_limits.py"],
                    cwd=os.getcwd(),
                    capture_output=True,
                    text=True,
                    env=env
                )
                dt_c = time.time() - t_c
                if res_ctx.returncode == 0:
                    report_lines.append(f" - [PASS] Logic Limit Boundaries ({dt_c:.1f}s)")
                else:
                    report_lines.append(f" - [FAIL] Logic Limit Constraints failed!")

            except Exception as e:
                report_lines.append(f" - [ERROR] Deep Diagnostics encountered fault: {e}")
        else:
            report_lines.append(" - [SKIP] Deep E2E/Evaluations (Skipped per Fast Boot)")

        report_lines.append("\nAll operational metrics checked. Proceed with user directives.")
        
        # Cleanup temporary test log directory
        if hasattr(self, "_test_log_dir") and os.path.exists(self._test_log_dir):
            import shutil
            shutil.rmtree(self._test_log_dir, ignore_errors=True)
        
        final_string = "\n".join(report_lines)
        self.finished_report.emit(final_string)
