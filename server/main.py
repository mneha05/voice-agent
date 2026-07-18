"""FastAPI entrypoint: serves the web client and the full-duplex audio WebSocket.

Run with:  python -m server.main   (or)   uvicorn server.main:app
"""
from __future__ import annotations

import json
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

from .config import config
from .session import Session

CLIENT_DIR = Path(__file__).resolve().parent.parent / "client"

app = FastAPI(title="Deepgram Voice Agent")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "stt": config.stt_model,
            "tts": config.tts_model, "llm": config.llm_provider}


@app.websocket("/ws")
async def ws_endpoint(ws: WebSocket) -> None:
    await ws.accept()

    async def send_json(obj: dict) -> None:
        await ws.send_text(json.dumps(obj))

    async def send_audio(pcm16: bytes) -> None:
        await ws.send_bytes(pcm16)

    session = Session(send_json, send_audio)
    try:
        await session.start()
        while True:
            msg = await ws.receive()
            if msg["type"] == "websocket.disconnect":
                break
            if (data := msg.get("bytes")) is not None:
                await session.feed_audio(data)         # mic PCM16 @ 16 kHz
            elif (text := msg.get("text")) is not None:
                # Reserved for client control messages (e.g. push-to-talk).
                _ = json.loads(text)
    except WebSocketDisconnect:
        pass
    finally:
        await session.close()


# Static client last so /ws and /health win the route match. html=True serves
# client/index.html at "/".
app.mount("/", StaticFiles(directory=str(CLIENT_DIR), html=True), name="client")


if __name__ == "__main__":
    config.require()
    print(f"\n  🎙️  Voice Agent live at  http://{config.host}:{config.port}\n")
    uvicorn.run(app, host=config.host, port=config.port, log_level="info")
