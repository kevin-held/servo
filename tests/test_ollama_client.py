import unittest
import threading
from unittest.mock import patch, MagicMock
from core.ollama_client import OllamaClient, ChatCancelled

class TestOllamaClient(unittest.TestCase):
    def setUp(self):
        self.client = OllamaClient(model="dummy-model", base_url="http://dummy:11434")

    @patch("core.ollama_client.requests.post")
    def test_unload_success(self, mock_post):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_post.return_value = mock_resp
        
        result = self.client.unload()
        self.assertTrue(result)
        mock_post.assert_called_once_with(
            "http://dummy:11434/api/generate",
            json={"model": "dummy-model", "keep_alive": 0},
            timeout=5
        )

    @patch("core.ollama_client.requests.post")
    def test_unload_failure(self, mock_post):
        import requests
        mock_post.side_effect = requests.RequestException("Network dropped")
        result = self.client.unload()
        self.assertFalse(result)

    @patch("core.ollama_client.requests.post")
    def test_chat_stream_cancellation(self, mock_post):
        cancel_event = threading.Event()
        
        # We mock iter_lines to yield one chunk, then we set the cancel_event, 
        # then yield another chunk to see if it raises ChatCancelled
        def mock_iter_lines():
            yield b'{"message": {"content": "Hello"}}'
            cancel_event.set()
            yield b'{"message": {"content": " World"}}'
            yield b'{"done": true, "done_reason": "stop"}'
        
        mock_resp = MagicMock()
        mock_resp.iter_lines.side_effect = mock_iter_lines
        mock_post.return_value = mock_resp

        generator = self.client._chat_stream_impl("sys", [], 10, cancel_event)
        
        # First chunk should succeed
        first = next(generator)
        self.assertEqual(first, "Hello")
        
        # Second chunk should raise ChatCancelled
        with self.assertRaises(ChatCancelled):
            next(generator)

    @patch("core.ollama_client.requests.post")
    def test_chat_stream_truncation_detection(self, mock_post):
        def mock_iter_lines():
            yield b'{"message": {"content": "A"}}'
            yield b'{"done": true, "done_reason": "length"}'
            
        mock_resp = MagicMock()
        mock_resp.iter_lines.side_effect = mock_iter_lines
        mock_post.return_value = mock_resp

        generator = self.client._chat_stream_impl("sys", [], 10, None)
        
        chunk = next(generator)
        self.assertEqual(chunk, "A")
        
        end_sentinel = next(generator)
        self.assertTrue(isinstance(end_sentinel, dict))
        self.assertTrue(end_sentinel.get("truncated"))
        self.assertTrue(end_sentinel.get("done"))

if __name__ == "__main__":
    unittest.main()
