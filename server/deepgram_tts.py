"""Streaming Text-to-Speech over Deepgram's Aura live WebSocket API.

Text is pushed in as the LLM produces it (clause by clause) and PCM audio streams
back immediately, so the first spoken syllable can leave before the LLM has even
finished its sentence. That overlap is most of the latency win.
"""
from __future__ import annotations

import asyncio
import json
from typing import Awaitable, Callable
from urllib.parse import urlencode

import websockets

from .config import config

TTS_URL = "wss://api.deepgram.com/v1/speak"

AudioHandler = Callable[[bytes], Awaitable[None]]   # called with raw PCM16 chunks


class DeepgramTTS:
    def __init__(self, on_audio: AudioHandler) -> None:
        self._on_audio = on_audio
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._recv_task: asyncio.Task | None = None
        self.closed = asyncio.Event()
        # Set when Deepgram signals it has rendered everything we asked for.
        self.flushed = asyncio.Event()

    async def connect(self) -> None:
        params = {
            "model": config.tts_model,
            "encoding": "linear16",
            "sample_rate": config.tts_sample_rate,
        }
        url = f"{TTS_URL}?{urlencode(params)}"
        self._ws = await websockets.connect(
            url,
            extra_headers={"Authorization": f"Token {config.deepgram_api_key}"},
            max_size=None,
        )
        self._recv_task = asyncio.create_task(self._recv_loop())

    async def speak(self, text: str) -> None:
        """Queue a chunk of text for synthesis (does not block on audio)."""
        if self._ws is not None and text.strip():
            await self._ws.send(json.dumps({"type": "Speak", "text": text}))

    async def flush(self) -> None:
        """Tell Deepgram to render everything buffered so far, right now."""
        if self._ws is not None:
            await self._ws.send(json.dumps({"type": "Flush"}))

    async def _recv_loop(self) -> None:
        assert self._ws is not None
        try:
            async for message in self._ws:
                if isinstance(message, bytes):
                    await self._on_audio(message)
                else:
                    # Control frame. "Flushed" means our Flush finished rendering
                    # — that's our "done speaking this turn" signal.
                    try:
                        if json.loads(message).get("type") == "Flushed":
                            self.flushed.set()
                    except (ValueError, AttributeError):
                        pass
        except websockets.ConnectionClosed:
            pass
        finally:
            self.closed.set()

    async def close(self) -> None:
        if self._recv_task:
            self._recv_task.cancel()
        if self._ws is not None:
            try:
                await self._ws.close()
            except websockets.ConnectionClosed:
                pass
        self.closed.set()
