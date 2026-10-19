# VoicePilot AI

A hands-free voice assistant for Android. It listens in the background,
understands what is said, and answers privately through your Bluetooth
earphones. Later milestones add voice control of the apps you allow.

So far the phone's microphone streams to the backend, which returns a live
transcript, spots questions and requests, and streams back short answers
shown in the app. Speaking answers aloud comes next.

```
app/       Flutter app (Android). Native Kotlin for the mic and background service.
backend/   Python FastAPI relay. Holds API keys, talks to speech services.
```

## What works now

- **Background listening switch.** Starts a foreground service that keeps the
  microphone and backend connection running after you close or swipe away the
  app. A notification shows while it listens, with a "Stop listening" button.
- **Voice assist switch.** Saved and shown in the notification. It will
  control spoken answers once text-to-speech lands in milestone 3.
- **Live transcript** with speaker numbers, from Deepgram streaming
  speech-to-text.
- **Answers.** When someone finishes a question or request, Claude decides
  whether it needs an answer and streams back one or two sentences. Small
  talk and statements get no answer.

## Run the backend

Needs Python 3.11+, a [Deepgram](https://deepgram.com) API key and an
[Anthropic](https://console.anthropic.com) API key.

```sh
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env   # then edit .env
set -a && source .env && set +a
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Run the tests with `python -m pytest`. They use fake speech and answer
services, so they need no keys.

## Test on your laptop

With the backend running:

- **Health check:** `GET http://localhost:8000/health` in Postman or a
  browser returns `{"ok": true}`.
- **Connection check in Postman:** New, WebSocket, URL
  `ws://localhost:8000/ws/session`, header `Authorization: Bearer <your token>`,
  Connect. You get `{"type":"ready"}`. Send `{"type":"stop"}` to close.
- **Full test with audio:** record a question, convert it, and stream it:

  ```sh
  ffmpeg -i question.m4a -ar 16000 -ac 1 -sample_fmt s16 question.wav
  python tools/stream_wav.py question.wav --token <your token>
  ```

  It prints what was heard and the answer, for example:

  ```
  [heard] What's the capital of Australia?
  [answering] What's the capital of Australia?
    The capital of Australia is Canberra.
  ```

## Run the app in Android Studio

1. Install [Flutter](https://docs.flutter.dev/get-started/install) and
   Android Studio, then in Android Studio go to Settings, Plugins and install
   **Flutter** (Dart comes with it).
2. Open the `app` folder in Android Studio and run `flutter pub get` when asked.
3. Connect your phone with USB debugging on, pick it in the device list and
   press Run.
4. In the app, open **Backend connection** and enter:
   - Backend URL: `ws://<your computer's IP>:8000/ws/session` (use
     `ws://10.0.2.2:8000/ws/session` on the emulator).
   - App token: the `VOICEPILOT_APP_TOKEN` from your `.env`.
5. Turn on **Background listening** and allow the microphone.

Debug builds allow plain `ws://` for local testing. Release builds need the
backend behind `wss://`.

## Privacy

Audio is streamed for transcription and never stored by the backend. Recording
other people needs their consent in many US states, including California, so
tell people when VoicePilot is listening.
