import unittest
from pathlib import Path
import sys

# Add project root to sys.path
_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.file_read import execute

class TestFileReadPagination(unittest.TestCase):
    def setUp(self):
        self.test_file = _ROOT / "tests" / "pagination_test.txt"
        # 40,000 chars should be 3 blocks (15k each)
        self.content = "A" * 40000
        self.test_file.write_text(self.content, encoding="utf-8")

    def tearDown(self):
        if self.test_file.exists():
            self.test_file.unlink()

    def test_block_zero(self):
        result = execute("tests/pagination_test.txt", block=0)
        self.assertEqual(len(result.split("\n\n")[0]), 15000)
        self.assertIn("[BLOCK 0 OF 2 - chars 0..14999 of 40000]", result)

    def test_block_one(self):
        result = execute("tests/pagination_test.txt", block=1)
        self.assertEqual(len(result.split("\n\n")[0]), 15000)
        self.assertIn("[BLOCK 1 OF 2 - chars 15000..29999 of 40000]", result)

    def test_block_two(self):
        result = execute("tests/pagination_test.txt", block=2)
        # 40,000 - 30,000 = 10,000
        self.assertEqual(len(result.split("\n\n")[0]), 10000)
        self.assertIn("[BLOCK 2 OF 2 - chars 30000..39999 of 40000]", result)

if __name__ == "__main__":
    unittest.main()
