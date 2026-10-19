"""Settings read from environment variables."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # Shared secret the phone app sends to open a session. Keeps the relay
    # from being used by anyone who finds the URL.
    app_token: str
    deepgram_api_key: str
    deepgram_model: str
    # Milliseconds of silence before the speech-to-text service marks the end
    # of an utterance. Lower is faster but cuts people off mid-sentence.
    endpointing_ms: int
    # Model and effort for detecting and answering questions. Lower effort
    # answers sooner.
    answer_model: str
    answer_effort: str


def load_settings() -> Settings:
    return Settings(
        app_token=os.environ.get("VOICEPILOT_APP_TOKEN", ""),
        deepgram_api_key=os.environ.get("DEEPGRAM_API_KEY", ""),
        deepgram_model=os.environ.get("DEEPGRAM_MODEL", "nova-3"),
        endpointing_ms=int(os.environ.get("VOICEPILOT_ENDPOINTING_MS", "300")),
        answer_model=os.environ.get("VOICEPILOT_ANSWER_MODEL", "claude-opus-5-5"),
        answer_effort=os.environ.get("VOICEPILOT_ANSWER_EFFORT", "low"),
    )
