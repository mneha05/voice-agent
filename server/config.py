"""Centralised configuration loaded from environment / .env."""
from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class Config:
    # Deepgram
    deepgram_api_key: str = os.getenv("DEEPGRAM_API_KEY", "")
    stt_model: str = os.getenv("DG_STT_MODEL", "nova-3")
    stt_language: str = os.getenv("DG_STT_LANGUAGE", "en")
    endpointing_ms: int = _int("DG_ENDPOINTING_MS", 300)
    utterance_end_ms: int = _int("DG_UTTERANCE_END_MS", 1000)
    tts_model: str = os.getenv("DG_TTS_MODEL", "aura-2-thalia-en")

    # Audio format contract between the browser, the server and Deepgram.
    # The mic captures/upsamples to 16 kHz PCM16; TTS returns 24 kHz PCM16.
    mic_sample_rate: int = 16000
    tts_sample_rate: int = 24000

    # LLM
    llm_provider: str = os.getenv("LLM_PROVIDER", "anthropic").lower()
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    system_prompt: str = os.getenv(
        "SYSTEM_PROMPT",
        "You are a warm, concise voice assistant. Keep replies to one or two "
        "short sentences unless asked for detail. You are being spoken to out "
        "loud, so never use markdown, lists, or emojis.",
    )

    # Server
    host: str = os.getenv("HOST", "127.0.0.1")
    port: int = _int("PORT", 8000)

    def require(self) -> None:
        """Fail fast with a friendly message if a critical key is missing."""
        missing = []
        if not self.deepgram_api_key:
            missing.append("DEEPGRAM_API_KEY")
        if self.llm_provider == "anthropic" and not self.anthropic_api_key:
            missing.append("ANTHROPIC_API_KEY")
        if self.llm_provider == "openai" and not self.openai_api_key:
            missing.append("OPENAI_API_KEY")
        if missing:
            raise RuntimeError(
                "Missing required env vars: "
                + ", ".join(missing)
                + ".  Copy .env.example -> .env and fill them in."
            )


config = Config()
