"""Latency measurement — the headline number of this project.

We track *mouth-to-response*: the wall-clock gap between the moment the user
stops speaking (Deepgram's end-of-turn signal) and the moment the first byte of
synthesized audio for the reply leaves the server toward the browser.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    k = (len(ordered) - 1) * (pct / 100.0)
    lo = int(k)
    hi = min(lo + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


@dataclass
class Turn:
    """Timing breakdown for a single user->agent exchange (all in ms)."""
    end_of_speech: float                 # monotonic seconds
    stt_final: float | None = None       # final transcript received
    llm_first_token: float | None = None
    tts_first_audio: float | None = None

    def _ms(self, a: float, b: float | None) -> float | None:
        return None if b is None else round((b - a) * 1000, 1)

    def breakdown(self) -> dict:
        return {
            "stt_finalize_ms": self._ms(self.end_of_speech, self.stt_final),
            "llm_first_token_ms": self._ms(self.end_of_speech, self.llm_first_token),
            "mouth_to_response_ms": self._ms(self.end_of_speech, self.tts_first_audio),
        }


@dataclass
class Metrics:
    samples: list[float] = field(default_factory=list)  # mouth-to-response ms
    _open: Turn | None = None

    def mark_end_of_speech(self) -> Turn:
        self._open = Turn(end_of_speech=time.monotonic())
        return self._open

    def mark(self, field_name: str) -> None:
        if self._open and getattr(self._open, field_name) is None:
            setattr(self._open, field_name, time.monotonic())

    def close_turn(self) -> dict | None:
        if not self._open:
            return None
        turn, self._open = self._open, None
        b = turn.breakdown()
        if b["mouth_to_response_ms"] is not None:
            self.samples.append(b["mouth_to_response_ms"])
        return b

    def summary(self) -> dict:
        s = self.samples
        return {
            "count": len(s),
            "p50_ms": round(_percentile(s, 50), 1),
            "p95_ms": round(_percentile(s, 95), 1),
            "min_ms": round(min(s), 1) if s else 0.0,
            "max_ms": round(max(s), 1) if s else 0.0,
        }
