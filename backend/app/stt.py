"""Streaming speech-to-text providers.

A provider takes raw audio chunks (16 kHz, 16-bit, mono PCM) and yields
transcript events. The session code only depends on the `SttStream`
protocol, so vendors can be swapped without touching it.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import AsyncIterator, Protocol
from urllib.parse import urlencode

import websockets

SAMPLE_RATE = 16_000


@dataclass(frozen=True)
class Transcript:
    text: str
    # False for interim guesses that may still change.
    is_final: bool
    # True when the speaker has paused long enough to end the utterance.
    speech_final: bool
    # Speaker number from diarization, or None if the provider has none.
    speaker: int | None = None

    def to_message(self) -> dict:
        return {
            "type": "transcript",
            "text": self.text,
            "is_final": self.is_final,
            "speech_final": self.speech_final,
            "speaker": self.speaker,
        }


class SttStream(Protocol):
    async def send_audio(self, chunk: bytes) -> None: ...

    async def finish(self) -> None: ...

    def transcripts(self) -> AsyncIterator[Transcript]: ...

    async def close(self) -> None: ...


class SttProvider(Protocol):
    async def open(self) -> SttStream: ...


class DeepgramStream:
    def __init__(self, ws: websockets.ClientConnection):
        self._ws = ws

    async def send_audio(self, chunk: bytes) -> None:
        await self._ws.send(chunk)

    async def finish(self) -> None:
        # Asks Deepgram to flush remaining results, then close.
        await self._ws.send(json.dumps({"type": "CloseStream"}))

    async def transcripts(self) -> AsyncIterator[Transcript]:
        async for raw in self._ws:
            if isinstance(raw, bytes):
                continue
            transcript = parse_deepgram_message(json.loads(raw))
            if transcript is not None:
                yield transcript

    async def close(self) -> None:
        await self._ws.close()


def parse_deepgram_message(message: dict) -> Transcript | None:
    if message.get("type") != "Results":
        return None
    alternatives = message.get("channel", {}).get("alternatives") or []
    if not alternatives:
        return None
    best = alternatives[0]
    text = best.get("transcript", "").strip()
    speech_final = bool(message.get("speech_final"))
    # An empty result still matters when it marks the end of an utterance.
    if not text and not speech_final:
        return None
    words = best.get("words") or []
    speaker = words[0].get("speaker") if words else None
    return Transcript(
        text=text,
        is_final=bool(message.get("is_final")),
        speech_final=speech_final,
        speaker=speaker,
    )


class DeepgramProvider:
    URL = "wss://api.deepgram.com/v1/listen"

    def __init__(self, api_key: str, model: str, endpointing_ms: int):
        self._api_key = api_key
        self._model = model
        self._endpointing_ms = endpointing_ms

    def url(self) -> str:
        params = {
            "model": self._model,
            "encoding": "linear16",
            "sample_rate": SAMPLE_RATE,
            "channels": 1,
            "interim_results": "true",
            "diarize": "true",
            "smart_format": "true",
            "endpointing": self._endpointing_ms,
        }
        return f"{self.URL}?{urlencode(params)}"

    async def open(self) -> DeepgramStream:
        ws = await websockets.connect(
            self.url(),
            additional_headers={"Authorization": f"Token {self._api_key}"},
        )
        return DeepgramStream(ws)


class FakeStream:
    """Test double: turns every audio chunk into a final transcript."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue[Transcript | None] = asyncio.Queue()
        self.received = 0

    async def send_audio(self, chunk: bytes) -> None:
        self.received += len(chunk)
        await self._queue.put(
            Transcript(text=f"{len(chunk)} bytes", is_final=True, speech_final=True, speaker=0)
        )

    async def finish(self) -> None:
        await self._queue.put(None)

    async def transcripts(self) -> AsyncIterator[Transcript]:
        while (item := await self._queue.get()) is not None:
            yield item

    async def close(self) -> None:
        await self._queue.put(None)


class FakeProvider:
    def __init__(self) -> None:
        self.streams: list[FakeStream] = []

    async def open(self) -> FakeStream:
        stream = FakeStream()
        self.streams.append(stream)
        return stream
