"""Stream a WAV file to a running backend, the way the phone does, and print
what comes back. Useful for testing on a laptop without the app.

The file must be 16 kHz, 16-bit, mono. Convert any recording with:
    ffmpeg -i input.m4a -ar 16000 -ac 1 -sample_fmt s16 question.wav

Usage:
    python tools/stream_wav.py question.wav --token mytoken123
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import wave

import websockets

CHUNK_SECONDS = 0.1


async def run(path: str, url: str, token: str, wait: float) -> None:
    with wave.open(path, "rb") as wav:
        if (wav.getframerate(), wav.getsampwidth(), wav.getnchannels()) != (16000, 2, 1):
            sys.exit(
                f"{path} must be 16 kHz, 16-bit, mono. Convert it with:\n"
                f"  ffmpeg -i {path} -ar 16000 -ac 1 -sample_fmt s16 out.wav"
            )
        audio = wav.readframes(wav.getnframes())

    chunk_bytes = int(16000 * 2 * CHUNK_SECONDS)
    async with websockets.connect(url, additional_headers={"Authorization": f"Bearer {token}"}) as ws:

        async def send_audio() -> None:
            for start in range(0, len(audio), chunk_bytes):
                await ws.send(audio[start : start + chunk_bytes])
                await asyncio.sleep(CHUNK_SECONDS)  # real-time pace, like a microphone
            # Trailing silence so the speech service sees the speaker stop.
            for _ in range(int(1.5 / CHUNK_SECONDS)):
                await ws.send(b"\x00" * chunk_bytes)
                await asyncio.sleep(CHUNK_SECONDS)
            await asyncio.sleep(wait)
            await ws.send(json.dumps({"type": "stop"}))

        sender = asyncio.create_task(send_audio())
        try:
            async for raw in ws:
                print_event(json.loads(raw))
        finally:
            sender.cancel()


def print_event(event: dict) -> None:
    kind = event.get("type")
    if kind == "transcript" and event.get("is_final"):
        print(f"[heard] {event['text']}")
    elif kind == "answer_start":
        print(f"[answering] {event['question']}\n  ", end="")
    elif kind == "answer_delta":
        print(event["text"], end="", flush=True)
    elif kind == "answer_end":
        print()
    elif kind in ("ready", "error"):
        print(f"[{kind}] {event.get('message', '')}".rstrip())


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("wav")
    parser.add_argument("--url", default="ws://localhost:8000/ws/session")
    parser.add_argument("--token", required=True, help="the VOICEPILOT_APP_TOKEN the backend runs with")
    parser.add_argument("--wait", type=float, default=5.0, help="seconds to wait for answers after the audio ends")
    args = parser.parse_args()
    try:
        asyncio.run(run(args.wav, args.url, args.token, args.wait))
    except websockets.exceptions.InvalidStatus as e:
        sys.exit(f"Backend refused the connection ({e.response.status_code}). Check --token.")
    except OSError as e:
        sys.exit(f"Could not reach {args.url}: {e}. Is the backend running?")


if __name__ == "__main__":
    main()
