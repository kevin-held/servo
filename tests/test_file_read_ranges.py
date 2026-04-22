import unittest
from pathlib import Path
import sys

# Add project root to sys.path
_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.file_read import execute

class TestFileReadRanges(unittest.TestCase):
    def setUp(self):
        self.test_file = _ROOT / "tests" / "range_test.txt"
        self.content = "\n".join([f"Line {i}" for i in range(1, 1001)])
        self.test_file.write_text(self.content, encoding="utf-8")

    def tearDown(self):
        if self.test_file.exists():
            self.test_file.unlink()

    def test_read_range(self):
        # Read lines 10 to 20
        result = execute("tests/range_test.txt", start_line=10, end_line=20)
        lines = result.splitlines()
        # The result includes the footer, so we check the core lines.
        # Line 10 to 20 inclusive is 11 lines.
        self.assertEqual(lines[0], "Line 10")
        self.assertEqual(lines[10], "Line 20")
        self.assertIn("[Showing lines 10-20 of 1000]", result)

    def test_read_range_overflow(self):
        # Read past end
        result = execute("tests/range_test.txt", start_line=990, end_line=1010)
        self.assertIn("Line 990", result)
        self.assertIn("Line 1000", result)
        self.assertIn("[Showing lines 990-1000 of 1000]", result)

    def test_read_start_only(self):
        # Default end_line is start_line + 500
        result = execute("tests/range_test.txt", start_line=100)
        self.assertIn("Line 100", result)
        self.assertIn("Line 600", result)
        self.assertIn("[Showing lines 100-600 of 1000]", result)

    def test_error_out_of_bounds(self):
        result = execute("tests/range_test.txt", start_line=2000)
        self.assertTrue(result.startswith("Error:"))

if __name__ == "__main__":
    unittest.main()
