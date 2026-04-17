import requests
import json
from tenacity import retry, stop_after_attempt, wait_exponential


class OllamaClient:
    """
    Thin wrapper around Ollama's HTTP API.
    Swapping to a cloud model later means changing base_url and model name — nothing else.
    """

    def __init__(
        self,
        model:       str = "gemma4:26b",
        base_url:    str = "http://localhost:11434",
    ):
        self.model       = model
        self.base_url    = base_url
        self.temperature = 0.6
        self.num_predict = 2048

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    def chat(self, system_prompt: str, messages: list, timeout: int = 300) -> tuple:
        """
        Send a chat request to Ollama.

        Returns:
            tuple: (content: str, truncated: bool)
                   truncated is True when the response was cut off by num_predict.
        """
        payload = {
            "model":    self.model,
            "messages": [{"role": "system", "content": system_prompt}] + messages,
            "stream":   False,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.num_predict,
            }
        }
        response = requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=timeout,
        )
        response.raise_for_status()
        data = response.json()
        content = data["message"]["content"]
        # Ollama returns done_reason: "length" when num_predict was the stopping condition
        truncated = data.get("done_reason") == "length"
        return content, truncated

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
    def chat_stream(self, system_prompt: str, messages: list, timeout: int = 300):
        """
        Stream a chat response from Ollama.

        Yields: str chunks of content.
        The last yielded item is a dict: {"done": True, "truncated": bool}
        to signal completion and whether num_predict was hit.
        """
        payload = {
            "model":    self.model,
            "messages": [{"role": "system", "content": system_prompt}] + messages,
            "stream":   True,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.num_predict,
            }
        }
        response = requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=timeout,
            stream=True
        )
        response.raise_for_status()
        truncated = False
        for line in response.iter_lines():
            if line:
                data = json.loads(line)
                if "message" in data and "content" in data["message"]:
                    yield data["message"]["content"]
                # The final chunk has done=True and includes done_reason
                if data.get("done"):
                    truncated = data.get("done_reason") == "length"
        # Yield a sentinel dict as the final item so callers can detect truncation
        yield {"done": True, "truncated": truncated}

    def clear_kv_cache(self) -> bool:
        """
        Forces Ollama to drop the model from VRAM, clearing the context history cache.
        """
        payload = {
            "model": self.model,
            "keep_alive": 0
        }
        try:
            requests.post(f"{self.base_url}/api/generate", json=payload, timeout=5)
            return True
        except Exception:
            return False

    def is_available(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return r.status_code == 200
        except Exception:
            return False

    def list_models(self) -> list[str]:
        try:
            r = requests.get(f"{self.base_url}/api/tags", timeout=5)
            return [m["name"] for m in r.json().get("models", [])]
        except Exception:
            return []

