import time
from openai import AsyncOpenAI
from .base import LLMClient, LLMResponse


class LocalModelClient(LLMClient):
    """Wraps Ollama or any OpenAI-compatible local inference server."""

    provider = "local"

    def __init__(self, model: str, base_url: str = "http://localhost:11434/v1"):
        self.model = model
        # Ollama exposes an OpenAI-compatible API — no real API key needed
        self._client = AsyncOpenAI(base_url=base_url, api_key="local")

    async def generate(self, prompt: str) -> LLMResponse:
        start = time.monotonic()
        response = await self._client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": prompt}],
        )
        latency_ms = int((time.monotonic() - start) * 1000)
        return LLMResponse(
            text=response.choices[0].message.content or "",
            model_version=response.model,
            tokens_input=response.usage.prompt_tokens if response.usage else 0,
            tokens_output=response.usage.completion_tokens if response.usage else 0,
            latency_ms=latency_ms,
        )
