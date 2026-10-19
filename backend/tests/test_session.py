import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import Settings
from app.main import UtteranceAssembler, create_app
from app.stt import FakeProvider, Transcript, parse_deepgram_message

TOKEN = "test-token"


class FakeAnswerer:
    """Answers every utterance in two pieces and records what it was asked."""

    def __init__(self) -> None:
        self.asked: list[tuple[str, list[str]]] = []

    async def answer(self, utterance, context):
        self.asked.append((utterance, list(context)))
        yield "It is "
        yield "noon."


def make_client(token: str = TOKEN) -> tuple[TestClient, FakeProvider, FakeAnswerer]:
    settings = Settings(
        app_token=token,
        deepgram_api_key="",
        deepgram_model="nova-3",
        endpointing_ms=300,
        answer_model="claude-opus-5-5",
        answer_effort="low",
    )
    stt = FakeProvider()
    answerer = FakeAnswerer()
    return TestClient(create_app(settings, stt, answerer)), stt, answerer


def test_health():
    client, _, _ = make_client()
    assert client.get("/health").json() == {"ok": True}


def test_rejects_missing_token():
    client, _, _ = make_client()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/session") as ws:
            ws.receive_json()


def test_rejects_when_no_token_configured():
    client, _, _ = make_client(token="")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/session", headers={"Authorization": "Bearer "}) as ws:
            ws.receive_json()


def test_streams_audio_and_returns_transcripts():
    client, stt, _ = make_client()
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with client.websocket_connect("/ws/session", headers=headers) as ws:
        assert ws.receive_json() == {"type": "ready"}
        ws.send_bytes(b"\x00\x01" * 160)
        event = ws.receive_json()
        assert event["type"] == "transcript"
        assert event["text"] == "320 bytes"
        assert event["is_final"] is True
        assert ws.receive_json()["type"] == "answer_start"
        assert ws.receive_json()["type"] == "answer_delta"
        assert ws.receive_json()["type"] == "answer_delta"
        assert ws.receive_json()["type"] == "answer_end"
        ws.send_text('{"type": "stop"}')
    assert stt.streams[0].received == 320


def test_parse_deepgram_results():
    message = {
        "type": "Results",
        "is_final": True,
        "speech_final": True,
        "channel": {"alternatives": [{"transcript": " What time is it? ", "words": [{"word": "what", "speaker": 1}]}]},
    }
    transcript = parse_deepgram_message(message)
    assert transcript is not None
    assert transcript.text == "What time is it?"
    assert transcript.speaker == 1
    assert transcript.speech_final is True


def test_parse_deepgram_ignores_empty_and_metadata():
    assert parse_deepgram_message({"type": "Metadata"}) is None
    empty = {"type": "Results", "channel": {"alternatives": [{"transcript": ""}]}}
    assert parse_deepgram_message(empty) is None


def test_parse_deepgram_keeps_empty_end_of_speech():
    message = {"type": "Results", "is_final": True, "speech_final": True,
               "channel": {"alternatives": [{"transcript": ""}]}}
    transcript = parse_deepgram_message(message)
    assert transcript is not None and transcript.text == "" and transcript.speech_final


def test_answers_each_utterance_with_earlier_context():
    client, _, answerer = make_client()
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with client.websocket_connect("/ws/session", headers=headers) as ws:
        assert ws.receive_json() == {"type": "ready"}
        ws.send_bytes(b"\x00" * 10)
        events = [ws.receive_json() for _ in range(5)]
        assert [e["type"] for e in events] == [
            "transcript", "answer_start", "answer_delta", "answer_delta", "answer_end",
        ]
        assert events[1] == {"type": "answer_start", "id": 1, "question": "10 bytes"}
        assert "".join(e["text"] for e in events if e["type"] == "answer_delta") == "It is noon."

        ws.send_bytes(b"\x00" * 20)
        events = [ws.receive_json() for _ in range(5)]
        assert events[1]["id"] == 2
        ws.send_text('{"type": "stop"}')
    assert answerer.asked == [("10 bytes", []), ("20 bytes", ["10 bytes"])]


def test_utterance_assembler_joins_final_pieces_until_pause():
    assembler = UtteranceAssembler()
    assert assembler.add(Transcript("what time", is_final=False, speech_final=False)) is None
    assert assembler.add(Transcript("What time", is_final=True, speech_final=False)) is None
    assert assembler.add(Transcript("is it?", is_final=True, speech_final=True)) == "What time is it?"
    assert assembler.add(Transcript("", is_final=True, speech_final=True)) is None
