#!/usr/bin/env python3
"""End-to-end latency benchmark.

Streams a spoken 16 kHz mono WAV file into the running server exactly like the
browser would, then prints the mouth-to-response latency the server reports.

Usage:
    # 1. start the server:  python -m server.main
    # 2. in another shell:
    python scripts/bench.py samples/hello.wav --repeat 10

Record a WAV on any OS with ffmpeg:
    ffmpeg -f dshow -i audio="Microphone" -ar 16000 -ac 1 -t 3 samples/hello.wav
"""
from __future__ import annotations

import argparse
import asyncio
import json
import wave

import websockets


async def one_run(url: str, frames: bytes, sample_rate: int) -> dict | None:
    async with websockets.connect(url, max_size=None) as ws:
        # Stream audio in 32 ms chunks, in real time, like a live mic.
        chunk = int(sample_rate * 0.032) * 2  # bytes (PCM16)
        result: dict | None = None

        async def reader():
            nonlocal result
            async for msg in ws:
                if isinstance(msg, bytes):
                    continue
                data = json.loads(msg)
                if data.get("type") == "latency":
                    result = data
                    return

        rtask = asyncio.create_task(reader())
        for i in range(0, len(frames), chunk):
            await ws.send(frames[i:i + chunk])
            await asyncio.sleep(0.032)
        # A little trailing silence so endpointing fires.
        await ws.send(b"\x00" * chunk * 20)
        try:
            await asyncio.wait_for(rtask, timeout=15)
        except asyncio.TimeoutError:
            rtask.cancel()
        return result


def load_wav(path: str) -> tuple[bytes, int]:
    with wave.open(path, "rb") as w:
        assert w.getnchannels() == 1, "WAV must be mono"
        assert w.getsampwidth() == 2, "WAV must be 16-bit PCM"
        return w.readframes(w.getnframes()), w.getframerate()


async def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("wav")
    ap.add_argument("--host", default="127.0.0.1:8000")
    ap.add_argument("--repeat", type=int, default=5)
    args = ap.parse_args()

    frames, sr = load_wav(args.wav)
    url = f"ws://{args.host}/ws"
    print(f"Benchmarking {url}  ({args.repeat} runs, {sr} Hz)\n")

    samples: list[float] = []
    for i in range(args.repeat):
        r = await one_run(url, frames, sr)
        if r and r.get("mouth_to_response_ms") is not None:
            ms = r["mouth_to_response_ms"]
            samples.append(ms)
            print(f"  run {i+1:2}:  mouth→response {ms:7.1f} ms   "
                  f"(stt {r.get('stt_finalize_ms')}, llm {r.get('llm_first_token_ms')})")
        else:
            print(f"  run {i+1:2}:  no response captured")

    if samples:
        samples.sort()
        p = lambda q: samples[min(len(samples) - 1, int(len(samples) * q))]
        print(f"\n  ── mouth→response ─────────────────")
        print(f"  p50 {p(0.5):7.1f} ms")
        print(f"  p95 {p(0.95):7.1f} ms")
        print(f"  min {min(samples):7.1f} ms   max {max(samples):7.1f} ms")


if __name__ == "__main__":
    asyncio.run(main())
