import argparse
import os
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt


def main():
    parser = argparse.ArgumentParser(description="Servo AI Assistant")
    parser.add_argument("--test", action="store_true", help="Run tests instead of starting the GUI")
    parser.add_argument("--e2e", action="store_true", help="Launch GUI and run an automated End-to-End visual test")
    parser.add_argument("--startup-tests", action="store_true", help="Launch GUI and immediately run silent startup unit tests")
    parser.add_argument("--deep-diagnostics", action="store_true", help="Forces slow E2E/Eval tasks into the startup test queue")
    parser.add_argument("--profile", type=str, help="State profile name. Uses state/state_<profile>.db and state/chroma_<profile>/")
    parser.add_argument(
        "--ollama-verbose",
        action="store_true",
        help="Mirror the Ollama streaming response to this shell's stderr. "
             "Output bypasses the Sentinel log and the agent's context — "
             "it is visible only in the terminal that launched main.py.",
    )
    parser.add_argument(
        "--chores",
        action="store_true",
        help="Run startup tests followed by automated initialization chores."
    )
    args = parser.parse_args()

    # Set the env var BEFORE importing anything that constructs an OllamaClient,
    # so the verbose flag is visible to the client's module-level reader on the
    # very first request of the session.
    if args.ollama_verbose:
        os.environ["OLLAMA_VERBOSE"] = "1"

    # Import after the env var is set — MainWindow → CoreLoop → OllamaClient.
    from gui.main_window import MainWindow

    if args.test:
        import unittest
        print("Running tests...")
        # Discover and run tests in the 'tests' directory
        test_suite = unittest.defaultTestLoader.discover('tests')
        test_runner = unittest.TextTestRunner(verbosity=2)
        result = test_runner.run(test_suite)
        sys.exit(not result.wasSuccessful())
        return

    # Enable high DPI scaling
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("Servo")
    app.setStyle("Fusion")

    window = MainWindow(
        run_startup_tests=args.startup_tests,
        run_deep_diagnostics=args.deep_diagnostics,
        run_startup_chores=args.chores,
        profile=args.profile
    )
    window.show()

    # v1.0.0 (D-20260421-14): Best-effort cleanup for Terminal / Interrupt exits
    import signal
    def handle_exit_signal(sig, frame):
        # Trigger the proper GUI close event so cleanup logic flows normally
        window.close()
        QApplication.quit()

    # Capture Ctrl+C and kill signals
    signal.signal(signal.SIGINT,  handle_exit_signal)
    signal.signal(signal.SIGTERM, handle_exit_signal)

    if args.e2e:
        from PySide6.QtCore import QTimer
        
        stage = [0]
        def on_response(text):
            if stage[0] == 0:
                stage[0] += 1
                def send_second():
                    prompt2 = "Great! Now for the second test: Read the contents of 'requirements.txt' using the 'filesystem' tool."
                    window.chat_panel.input_field.setText(prompt2)
                    window.chat_panel.send_btn.click()
                # Wait slightly to let the visual UI settle before sending the second test
                QTimer.singleShot(1500, send_second)

        def run_e2e():
            window.loop.response_ready.connect(on_response)
            prompt = (
                "I want you to test your tools. For the first test: Use the 'filesystem' tool to list the files in the current directory ('.')."
            )
            window.chat_panel.input_field.setText(prompt)
            window.chat_panel.send_btn.click()
            
        # Wait 1000ms to ensure the model connects and is ready before starting
        QTimer.singleShot(1000, run_e2e)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
