"""VoicePilot backend relay.

The phone opens one WebSocket per listening session at /ws/session:
- phone -> server: binary frames of 16 kHz, 16-bit, mono PCM audio, and
  text frames with JSON control messages ({"type": "stop"}).
- server -> phone: JSON text frames:
  {"type": "ready"} once speech-to-text is connected,
  {"type": "transcript", ...} as speech is recognised,
  {"type": "answer_start", "id", "question"}, {"type": "answer_delta", "id",
  "text"} and {"type": "answer_end", "id"} when a question is answered,
  {"type": "error", "message"} if something fails.

API keys for speech and AI services live only here, never on the phone.
"""

from __future__ import annotations

import asyncio
import hmac
import json
import logging
from collections import deque

import anthropic
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, status

from .answer import Answerer, ClaudeAnswerer
from .config import Settings, load_settings
from .stt import DeepgramProvider, SttProvider, Transcript

log = logging.getLogger("voicepilot")

# How many earlier utterances the answerer sees for context.
CONTEXT_UTTERANCES = 6


def create_app(
    settings: Settings | None = None,
    stt: SttProvider | None = None,
    answerer: Answerer | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    stt = stt or DeepgramProvider(
        settings.deepgram_api_key, settings.deepgram_model, settings.endpointing_ms
    )
    answerer = answerer or ClaudeAnswerer(
        anthropic.AsyncAnthropic(), settings.answer_model, settings.answer_effort
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

        send_lock = asyncio.Lock()

        async def send(message: dict) -> None:
            # Transcripts and answers are sent from different tasks.
            async with send_lock:
                await ws.send_json(message)

        await send({"type": "ready"})

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

        utterances = UtteranceAssembler()
        context: deque[str] = deque(maxlen=CONTEXT_UTTERANCES)
        answer_task: asyncio.Task | None = None
        answer_id = 0

        async def answer(id: int, question: str, earlier: list[str]) -> None:
            started = False
            try:
                async for text in answerer.answer(question, earlier):
                    if not started:
                        await send({"type": "answer_start", "id": id, "question": question})
                        started = True
                    await send({"type": "answer_delta", "id": id, "text": text})
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("answering failed")
                await send({"type": "error", "message": "could not get an answer"})
            finally:
                if started:
                    await send({"type": "answer_end", "id": id})

        async def stt_to_phone() -> None:
            nonlocal answer_task, answer_id
            async for transcript in stream.transcripts():
                if transcript.text:
                    await send(transcript.to_message())
                utterance = utterances.add(transcript)
                if utterance is None:
                    continue
                # Newer speech replaces an answer still in progress.
                if answer_task and not answer_task.done():
                    answer_task.cancel()
                answer_id += 1
                answer_task = asyncio.create_task(answer(answer_id, utterance, list(context)))
                context.append(utterance)

        upload = asyncio.create_task(phone_to_stt())
        try:
            await stt_to_phone()
            if answer_task:
                await answer_task
        except Exception:
            log.exception("speech-to-text stream failed")
        finally:
            upload.cancel()
            if answer_task:
                answer_task.cancel()
            await stream.close()
            try:
                await ws.close()
            except RuntimeError:
                pass  # already closed by the phone

    return app


class UtteranceAssembler:
    """Joins final transcript pieces until the speaker pauses."""

    def __init__(self) -> None:
        self._parts: list[str] = []

    def add(self, transcript: Transcript) -> str | None:
        """Returns the whole utterance when it ends, otherwise None."""
        if transcript.is_final and transcript.text:
            self._parts.append(transcript.text)
        if not transcript.speech_final or not self._parts:
            return None
        utterance = " ".join(self._parts)
        self._parts = []
        return utterance


def _authorized(ws: WebSocket, expected: str) -> bool:
    if not expected:
        # No token configured: refuse everything rather than run an open relay.
        return False
    header = ws.headers.get("authorization", "")
    supplied = header.removeprefix("Bearer ").strip()
    return hmac.compare_digest(supplied, expected)


app = create_app()
