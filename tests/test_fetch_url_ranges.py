import unittest
from unittest.mock import patch, MagicMock
import sys
from pathlib import Path

# Add project root to sys.path
_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from tools.fetch_url import execute

class TestFetchUrlRanges(unittest.TestCase):

    @patch("urllib.request.urlopen")
    def test_fetch_url_ranges(self, mock_urlopen):
        # Mocking the response
        mock_response = MagicMock()
        content = "\n".join([f"Line {i}" for i in range(1, 1001)])
        mock_response.read.return_value = content.encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        # Test reading lines 10 to 20
        result = execute("http://example.com", start_line=10, end_line=20)
        lines = result.splitlines()
        
        # Check first and last line of body
        self.assertEqual(lines[0], "Line 10")
        self.assertEqual(lines[10], "Line 20")
        self.assertIn("[Showing lines 10-20 of 1000]", result)

    @patch("urllib.request.urlopen")
    def test_fetch_url_block_fallback(self, mock_urlopen):
        mock_response = MagicMock()
        # 40k chars
        content = "A" * 40000
        mock_response.read.return_value = content.encode("utf-8")
        mock_response.__enter__.return_value = mock_response
        mock_urlopen.return_value = mock_response

        result = execute("http://example.com", block=1)
        self.assertIn("[BLOCK 1 OF 2 - chars 15000..29999 of 40000]", result)

if __name__ == "__main__":
    unittest.main()
