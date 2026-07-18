"""Streaming LLM completions, provider-agnostic.

Yields text deltas as fast as the model emits them so downstream TTS can start
speaking before the full answer exists. Swap providers with LLM_PROVIDER=...
"""
from __future__ import annotations

from typing import AsyncIterator

from .config import config

# Conversation history is a list of {"role": "user"|"assistant", "content": str}.
Messages = list[dict[str, str]]


async def stream_completion(history: Messages) -> AsyncIterator[str]:
    if config.llm_provider == "openai":
        async for delta in _openai_stream(history):
            yield delta
    else:
        async for delta in _anthropic_stream(history):
            yield delta


async def _anthropic_stream(history: Messages) -> AsyncIterator[str]:
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=config.anthropic_api_key)
    async with client.messages.stream(
        model=config.anthropic_model,
        max_tokens=300,
        system=config.system_prompt,
        messages=history,
    ) as stream:
        async for text in stream.text_stream:
            yield text


async def _openai_stream(history: Messages) -> AsyncIterator[str]:
    from openai import AsyncOpenAI

    client = AsyncOpenAI(api_key=config.openai_api_key)
    messages = [{"role": "system", "content": config.system_prompt}, *history]
    stream = await client.chat.completions.create(
        model=config.openai_model,
        max_tokens=300,
        messages=messages,
        stream=True,
    )
    async for chunk in stream:
        delta = chunk.choices[0].delta.content
        if delta:
            yield delta
