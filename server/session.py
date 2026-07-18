"""The conversation orchestrator: a full-duplex state machine tying STT, the LLM
and TTS together with barge-in.

    LISTENING ──user speaks──▶ (accumulate transcript)
        ▲                         │ end-of-turn
        │                         ▼
        │                     THINKING ──first token──▶ SPEAKING
        └───────────── barge-in ◀──────────────────────────┘
         (user starts talking again while the agent is thinking/speaking)
"""
from __future__ import annotations

import asyncio
import re
from enum import Enum, auto
from typing import Awaitable, Callable

from .deepgram_stt import DeepgramSTT
from .deepgram_tts import DeepgramTTS
from .llm import stream_completion
from .metrics import Metrics

# Flush a chunk to TTS as soon as we cross a clause boundary — this is what lets
# the agent start talking before the sentence is finished.
_BOUNDARY = re.compile(r"[.!?;:,]\s|\n")


class State(Enum):
    LISTENING = auto()
    THINKING = auto()
    SPEAKING = auto()


class Session:
    def __init__(
        self,
        send_json: Callable[[dict], Awaitable[None]],
        send_audio: Callable[[bytes], Awaitable[None]],
    ) -> None:
        self._send_json = send_json
        self._send_audio = send_audio
        self.state = State.LISTENING
        self.metrics = Metrics()
        self.history: list[dict[str, str]] = []

        self._stt = DeepgramSTT(self._on_stt_event)
        self._final_parts: list[str] = []
        self._agent_task: asyncio.Task | None = None

    # ---- lifecycle -------------------------------------------------------
    async def start(self) -> None:
        await self._stt.connect()
        await self._set_state(State.LISTENING)

    async def feed_audio(self, pcm16: bytes) -> None:
        await self._stt.send_audio(pcm16)

    async def close(self) -> None:
        await self._cancel_agent()
        await self._stt.close()

    async def _set_state(self, state: State) -> None:
        self.state = state
        await self._send_json({"type": "state", "value": state.name.lower()})

    # ---- STT event handling ---------------------------------------------
    async def _on_stt_event(self, evt: dict) -> None:
        kind = evt.get("type")

        if kind == "UtteranceEnd":
            await self._maybe_finalize_turn()
            return

        if kind != "Results":
            return  # Metadata, SpeechStarted, etc.

        alt = evt.get("channel", {}).get("alternatives", [{}])[0]
        transcript = (alt.get("transcript") or "").strip()
        is_final = evt.get("is_final", False)
        speech_final = evt.get("speech_final", False)

        if transcript:
            # Any words while the agent holds the floor => user is interrupting.
            if self.state in (State.THINKING, State.SPEAKING):
                await self._barge_in()
            await self._send_json(
                {"type": "transcript", "text": transcript, "final": is_final}
            )

        if is_final and transcript:
            self._final_parts.append(transcript)

        if speech_final:
            await self._maybe_finalize_turn()

    async def _maybe_finalize_turn(self) -> None:
        text = " ".join(self._final_parts).strip()
        self._final_parts.clear()
        if not text or self.state != State.LISTENING:
            return
        self.metrics.mark_end_of_speech()
        self.metrics.mark("stt_final")
        self.history.append({"role": "user", "content": text})
        await self._send_json({"type": "user", "text": text})
        self._agent_task = asyncio.create_task(self._run_agent_turn())

    # ---- barge-in --------------------------------------------------------
    async def _barge_in(self) -> None:
        await self._cancel_agent()
        # Tell the browser to drop everything still in its playback buffer.
        await self._send_json({"type": "clear"})
        self._final_parts.clear()
        await self._set_state(State.LISTENING)

    async def _cancel_agent(self) -> None:
        if self._agent_task and not self._agent_task.done():
            self._agent_task.cancel()
            try:
                await self._agent_task
            except asyncio.CancelledError:
                pass
        self._agent_task = None

    # ---- the agent turn: LLM -> TTS, fully streamed ----------------------
    async def _run_agent_turn(self) -> None:
        await self._set_state(State.THINKING)
        tts = DeepgramTTS(self._on_tts_audio)
        await tts.connect()

        spoken = ""
        buffer = ""
        try:
            async for delta in stream_completion(self.history):
                self.metrics.mark("llm_first_token")
                spoken += delta
                buffer += delta
                # Emit each completed clause to TTS the instant it's ready.
                while (m := _BOUNDARY.search(buffer)) is not None:
                    cut = m.end()
                    chunk, buffer = buffer[:cut], buffer[cut:]
                    if self.state == State.THINKING:
                        await self._set_state(State.SPEAKING)
                    await tts.speak(chunk)
            if buffer.strip():
                if self.state == State.THINKING:
                    await self._set_state(State.SPEAKING)
                await tts.speak(buffer)

            await tts.flush()
            await self._send_json({"type": "agent", "text": spoken.strip()})
            self.history.append({"role": "assistant", "content": spoken.strip()})
            # Give the audio tail time to drain before returning to listening.
            await asyncio.wait_for(tts.closed.wait(), timeout=15)
        except asyncio.CancelledError:
            raise  # barge-in: propagate so _cancel_agent completes cleanly
        finally:
            await tts.close()
            brk = self.metrics.close_turn()
            if brk and brk.get("mouth_to_response_ms") is not None:
                await self._send_json({"type": "latency", **brk})
                await self._send_json({"type": "metrics", **self.metrics.summary()})
            if self.state != State.LISTENING:
                await self._set_state(State.LISTENING)

    async def _on_tts_audio(self, pcm16: bytes) -> None:
        self.metrics.mark("tts_first_audio")   # first byte = the headline latency
        await self._send_audio(pcm16)
