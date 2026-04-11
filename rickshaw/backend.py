"""Rickshaw Backend — Ollama OpenAI-compatible client."""
import requests
from . import config


class Backend:
    def __init__(self, base_url=None, model=None, temperature=None):
        self.base_url = (base_url or config.OLLAMA_URL).rstrip("/")
        self.model = model or config.DEFAULT_MODEL
        self.temperature = temperature or config.TEMPERATURE

    def chat(self, messages, tools=None, model=None, temperature=None):
        """Send chat completion. Returns {content, tool_calls, finish_reason}."""
        payload = {
            "model": model or self.model,
            "messages": messages,
            "temperature": temperature or self.temperature,
        }
        if tools:
            payload["tools"] = tools

        resp = requests.post(
            f"{self.base_url}/chat/completions",
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=180,
        )
        resp.raise_for_status()
        data = resp.json()

        choice = data["choices"][0]
        message = choice["message"]

        # Strip <think>...</think> blocks from content
        content = message.get("content") or ""
        if "<think>" in content:
            import re
            content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()

        return {
            "content": content,
            "tool_calls": message.get("tool_calls"),
            "finish_reason": choice.get("finish_reason"),
        }

    def ping(self):
        """Check if Ollama is reachable."""
        try:
            resp = requests.get(
                self.base_url.replace("/v1", ""), timeout=5
            )
            return resp.ok
        except Exception:
            return False
