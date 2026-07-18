"""Streaming Speech-to-Text over Deepgram's live WebSocket API.

We talk to Deepgram with a raw WebSocket instead of the SDK on purpose: the wire
protocol is small, extremely stable, and keeps the latency path transparent so
you can see exactly what is happening on every millisecond.
"""
from __future__ import annotations

import asyncio
import json
from typing import Awaitable, Callable
from urllib.parse import urlencode

import websockets

from .config import config

STT_URL = "wss://api.deepgram.com/v1/listen"

# Event = one JSON message from Deepgram. Handler is async.
EventHandler = Callable[[dict], Awaitable[None]]


class DeepgramSTT:
    def __init__(self, on_event: EventHandler) -> None:
        self._on_event = on_event
        self._ws: websockets.WebSocketClientProtocol | None = None
        self._recv_task: asyncio.Task | None = None
        self._keepalive_task: asyncio.Task | None = None

    async def connect(self) -> None:
        params = {
            "model": config.stt_model,
            "language": config.stt_language,
            "encoding": "linear16",
            "sample_rate": config.mic_sample_rate,
            "channels": 1,
            "interim_results": "true",   # partial transcripts -> instant UI + barge-in
            "endpointing": config.endpointing_ms,
            "utterance_end_ms": config.utterance_end_ms,
            "vad_events": "true",        # SpeechStarted events power barge-in
            "smart_format": "true",
        }
        url = f"{STT_URL}?{urlencode(params)}"
        self._ws = await websockets.connect(
            url,
            extra_headers={"Authorization": f"Token {config.deepgram_api_key}"},
            max_size=None,
        )
        self._recv_task = asyncio.create_task(self._recv_loop())
        self._keepalive_task = asyncio.create_task(self._keepalive_loop())

    async def send_audio(self, pcm16: bytes) -> None:
        if self._ws is not None:
            await self._ws.send(pcm16)

    async def _recv_loop(self) -> None:
        assert self._ws is not None
        try:
            async for message in self._ws:
                if isinstance(message, bytes):
                    continue
                await self._on_event(json.loads(message))
        except websockets.ConnectionClosed:
            pass

    async def _keepalive_loop(self) -> None:
        """Deepgram closes idle sockets after ~10s; nudge it during silence."""
        try:
            while True:
                await asyncio.sleep(5)
                if self._ws is not None:
                    await self._ws.send(json.dumps({"type": "KeepAlive"}))
        except (websockets.ConnectionClosed, asyncio.CancelledError):
            pass

    async def close(self) -> None:
        for task in (self._keepalive_task, self._recv_task):
            if task:
                task.cancel()
        if self._ws is not None:
            try:
                await self._ws.send(json.dumps({"type": "CloseStream"}))
                await self._ws.close()
            except websockets.ConnectionClosed:
                pass
