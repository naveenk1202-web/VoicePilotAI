import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app.config import Settings
from app.main import create_app
from app.stt import FakeProvider, parse_deepgram_message

TOKEN = "test-token"


def make_client(token: str = TOKEN) -> tuple[TestClient, FakeProvider]:
    settings = Settings(app_token=token, deepgram_api_key="", deepgram_model="nova-3", endpointing_ms=300)
    stt = FakeProvider()
    return TestClient(create_app(settings, stt)), stt


def test_health():
    client, _ = make_client()
    assert client.get("/health").json() == {"ok": True}


def test_rejects_missing_token():
    client, _ = make_client()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/session") as ws:
            ws.receive_json()


def test_rejects_when_no_token_configured():
    client, _ = make_client(token="")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/session", headers={"Authorization": "Bearer "}) as ws:
            ws.receive_json()


def test_streams_audio_and_returns_transcripts():
    client, stt = make_client()
    headers = {"Authorization": f"Bearer {TOKEN}"}
    with client.websocket_connect("/ws/session", headers=headers) as ws:
        assert ws.receive_json() == {"type": "ready"}
        ws.send_bytes(b"\x00\x01" * 160)
        event = ws.receive_json()
        assert event["type"] == "transcript"
        assert event["text"] == "320 bytes"
        assert event["is_final"] is True
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
