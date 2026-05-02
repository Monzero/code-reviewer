from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMResponse:
    text: str
    model_version: str
    tokens_input: int
    tokens_output: int
    latency_ms: int


class LLMClient(ABC):
    provider: str
    model: str

    @abstractmethod
    async def generate(self, prompt: str) -> LLMResponse:
        pass
