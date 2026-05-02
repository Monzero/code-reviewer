import time
from openai import AsyncOpenAI
from .base import LLMClient, LLMResponse


class OpenAIClient(LLMClient):
    provider = "openai"

    def __init__(self, model: str):
        self.model = model
        self._client = AsyncOpenAI()

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
            tokens_input=response.usage.prompt_tokens,
            tokens_output=response.usage.completion_tokens,
            latency_ms=latency_ms,
        )
