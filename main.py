import argparse
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from gui.main_window import MainWindow


def main():
    parser = argparse.ArgumentParser(description="Servo AI Assistant")
    parser.add_argument("--test", action="store_true", help="Run tests instead of starting the GUI")
    parser.add_argument("--e2e", action="store_true", help="Launch GUI and run an automated End-to-End visual test")
    args = parser.parse_args()

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

    window = MainWindow()
    window.show()

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
