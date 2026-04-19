import os
import sys
import time
import requests
import json
import threading
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_not_exception_type,
)


# ─────────────────────────────────────────────────────────────────────
# Verbose shell output — strictly out-of-band from the agent's context.
#
# When OLLAMA_VERBOSE is set, raw streaming chunks are mirrored to the
# original process stderr (sys.__stderr__) so they appear in the shell
# that launched `python main.py`. This channel is NOT the Sentinel log
# (which writes JSON to logs/sentinel.jsonl), and it is NOT what feeds
# conversation history or tool context — those come from chat()'s
# returned `content` string. A redirection of sys.stderr elsewhere in
# the process cannot capture __stderr__, so the stream stays visible
# in the terminal and nowhere else.
#
# Enable with --ollama-verbose on main.py, or by setting the env var
# directly: OLLAMA_VERBOSE=1 python main.py
# ─────────────────────────────────────────────────────────────────────
def _verbose_enabled() -> bool:
    return os.environ.get("OLLAMA_VERBOSE", "").lower() in ("1", "true", "yes", "on")


def _verbose_write(s: str) -> None:
    """Write directly to the original stderr. Never raises, never logs."""
    try:
        sys.__stderr__.write(s)
        sys.__stderr__.flush()
    except Exception:
        pass


class ChatCancelled(Exception):
    """
    Raised when a chat call is cancelled via cancel_event.
    Callers (notably CoreLoop) should catch this and re-enter PERCEIVE
    with the user's new input instead of treating it as a generic error.
    """
    pass


class OllamaClient:
    """
    Thin wrapper around Ollama's HTTP API.
    Swapping to a cloud model later means changing base_url and model name — nothing else.

    Both chat() and chat_stream() accept an optional cancel_event (threading.Event).
    When set during an in-flight request, the underlying stream closes cooperatively
    and ChatCancelled is raised. This lets user input interrupt a long model call
    (the loop checks _pending_input between cycles anyway, but cancellation is what
    makes that check meaningful when a 26B model is taking minutes to respond).
    """

    def __init__(
        self,
        model:       str = "gemma4:26b",
        base_url:    str = "http://localhost:11434",
    ):
        self.model       = model
        self.base_url    = base_url
        self.temperature = 0.6
        self.num_predict = 16384 # manual testing stable with this param, not too high

    # ─────────────────────────────────────────────────────────────
    # Internal streaming impl — no retry. Everything cancellable.
    # ─────────────────────────────────────────────────────────────
    def _chat_stream_impl(
        self,
        system_prompt: str,
        messages:      list,
        timeout:       int,
        cancel_event:  threading.Event | None,
    ):
        payload = {
            "model":    self.model,
            "messages": [{"role": "system", "content": system_prompt}] + messages,
            "stream":   True,
            "options": {
                "temperature": self.temperature,
                "num_predict": self.num_predict,
            }
        }
        verbose = _verbose_enabled()
        t_start = time.monotonic()
        if verbose:
            ts = time.strftime("%H:%M:%S")
            _verbose_write(
                f"\n\n\033[2m[ollama {ts}] {self.model} ── stream begin "
                f"(temp={self.temperature}, num_predict={self.num_predict})\033[0m\n"
            )

        response = requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=timeout,
            stream=True,
        )
        response.raise_for_status()
        truncated = False
        try:
            for line in response.iter_lines():
                # Cooperative cancellation — checked every chunk boundary.
                if cancel_event is not None and cancel_event.is_set():
                    if verbose:
                        _verbose_write("\n\033[2m[ollama] ── cancelled mid-stream\033[0m\n")
                    raise ChatCancelled("Chat cancelled mid-stream by cancel_event")
                if line:
                    data = json.loads(line)
                    if "message" in data and "content" in data["message"]:
                        chunk = data["message"]["content"]
                        if verbose:
                            _verbose_write(chunk)
                        yield chunk
                    if data.get("done"):
                        truncated = data.get("done_reason") == "length"
        finally:
            try:
                response.close()
            except Exception:
                pass
        if verbose:
            elapsed = time.monotonic() - t_start
            tag = " (truncated by num_predict)" if truncated else ""
            _verbose_write(
                f"\n\033[2m[ollama] ── stream end{tag} in {elapsed:.1f}s\033[0m\n\n"
            )
        # Sentinel final item — callers detect truncation off this.
        yield {"done": True, "truncated": truncated}

    # ─────────────────────────────────────────────────────────────
    # Public API
    # ─────────────────────────────────────────────────────────────
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_not_exception_type(ChatCancelled),
    )
    def chat(
        self,
        system_prompt: str,
        messages:      list,
        timeout:       int = 300,
        cancel_event:  threading.Event | None = None,
    ) -> tuple:
        """
        Send a chat request to Ollama.

        Internally uses the streaming impl so cancel_event can interrupt mid-response.
        The API contract (returning (content, truncated)) is preserved, so existing
        callers don't need to care that the transport is streaming under the hood.

        Returns:
            tuple: (content: str, truncated: bool)
                   truncated is True when num_predict was the stopping condition.
        Raises:
            ChatCancelled if cancel_event was set during the request.
        """
        content = ""
        truncated = False
        for chunk in self._chat_stream_impl(system_prompt, messages, timeout, cancel_event):
            if isinstance(chunk, dict) and chunk.get("done"):
                truncated = chunk.get("truncated", False)
            else:
                content += chunk
        return content, truncated

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_not_exception_type(ChatCancelled),
    )
    def chat_stream(
        self,
        system_prompt: str,
        messages:      list,
        timeout:       int = 300,
        cancel_event:  threading.Event | None = None,
    ):
        """
        Stream a chat response from Ollama.

        Yields: str chunks of content, then a final dict:
            {"done": True, "truncated": bool}

        Raises:
            ChatCancelled if cancel_event was set during iteration.
        """
        yield from self._chat_stream_impl(system_prompt, messages, timeout, cancel_event)

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
