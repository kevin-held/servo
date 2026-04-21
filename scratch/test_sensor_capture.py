import sys
import json
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure project root is on the path
_ROOT = Path(__file__).parent.parent.resolve()
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.ollama_client import OllamaClient

class TestOllamaSensor(unittest.TestCase):
    @patch("core.ollama_client.requests.post")
    def test_token_capture(self, mock_post):
        client = OllamaClient()
        
        # Mock a streaming response
        mock_resp = MagicMock()
        mock_resp.iter_lines.return_value = [
            b'{"message": {"content": "Hello"}}',
            b'{"done": true, "prompt_eval_count": 123, "eval_count": 45}'
        ]
        mock_post.return_value = mock_resp
        
        # Trigger the chat
        client.chat("sys", [{"role": "user", "content": "hi"}])
        
        # Verify capture
        self.assertEqual(client.last_prompt_tokens, 123)
        self.assertEqual(client.last_response_tokens, 45)

if __name__ == "__main__":
    unittest.main()
