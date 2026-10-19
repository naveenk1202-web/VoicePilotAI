"""VoicePilot backend relay.

The phone opens one WebSocket per listening session at /ws/session:
- phone -> server: binary frames of 16 kHz, 16-bit, mono PCM audio, and
  text frames with JSON control messages ({"type": "stop"}).
- server -> phone: JSON text frames, {"type": "ready"} once speech-to-text
  is connected, then {"type": "transcript", ...} events, and
  {"type": "error", "message": ...} if something fails.

API keys for speech services live only here, never on the phone.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status

from .config import Settings, load_settings
from .stt import DeepgramProvider, SttProvider

log = logging.getLogger("voicepilot")


def create_app(settings: Settings | None = None, stt: SttProvider | None = None) -> FastAPI:
    settings = settings or load_settings()
    stt = stt or DeepgramProvider(
        settings.deepgram_api_key, settings.deepgram_model, settings.endpointing_ms
    )
    app = FastAPI(title="VoicePilot backend")

    @app.get("/health")
    async def health() -> dict:
        return {"ok": True}

    @app.websocket("/ws/session")
    async def session(ws: WebSocket) -> None:
        if not _authorized(ws, settings.app_token):
            await ws.close(code=status.WS_1008_POLICY_VIOLATION)
            return
        await ws.accept()

        try:
            stream = await stt.open()
        except Exception:
            log.exception("could not open speech-to-text stream")
            await ws.send_json({"type": "error", "message": "speech-to-text unavailable"})
            await ws.close(code=status.WS_1011_INTERNAL_ERROR)
            return

        await ws.send_json({"type": "ready"})

        async def phone_to_stt() -> None:
            try:
                while True:
                    message = await ws.receive()
                    if message["type"] == "websocket.disconnect":
                        break
                    if message.get("bytes"):
                        await stream.send_audio(message["bytes"])
                    elif message.get("text"):
                        control = json.loads(message["text"])
                        if control.get("type") == "stop":
                            break
            except WebSocketDisconnect:
                pass
            finally:
                await stream.finish()

        async def stt_to_phone() -> None:
            async for transcript in stream.transcripts():
                await ws.send_json(transcript.to_message())

        upload = asyncio.create_task(phone_to_stt())
        try:
            await stt_to_phone()
        except Exception:
            log.exception("speech-to-text stream failed")
        finally:
            upload.cancel()
            await stream.close()
            try:
                await ws.close()
            except RuntimeError:
                pass  # already closed by the phone

    return app


def _authorized(ws: WebSocket, expected: str) -> bool:
    if not expected:
        # No token configured: refuse everything rather than run an open relay.
        return False
    header = ws.headers.get("authorization", "")
    supplied = header.removeprefix("Bearer ").strip()
    return hmac.compare_digest(supplied, expected)


app = create_app()
