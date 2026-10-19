"""Decides whether an utterance needs an answer, and streams the answer.

One model call does both: the model either replies with a short spoken
answer or with the single word NONE. Streaming starts as soon as the first
few characters show it is not NONE, so the answer reaches the phone (and
later, text-to-speech) without waiting for the whole reply.
"""

from __future__ import annotations

from typing import AsyncIterator, Protocol, Sequence

import anthropic

NO_ANSWER = "NONE"

SYSTEM_PROMPT = f"""\
You are VoicePilot, a voice assistant. Your replies are spoken privately \
into the user's earphones while they are talking with someone or going \
about their day, so they must be quick to hear.

You receive one utterance transcribed from live speech, plus a few earlier \
utterances for context. Transcripts can contain recognition mistakes; read \
them for what was most likely said.

If the utterance is a question or a request for information you can help \
with, answer it in one or two short sentences, the way you would say it out \
loud: no lists, no markdown, no preamble, and no repeating the question.

If the utterance is not a question or request (a statement, small talk, a \
half-finished sentence, background noise), reply with exactly {NO_ANSWER} \
and nothing else."""

# Models that accept server-side refusal fallbacks ("default" mode).
_FALLBACK_MODELS = {"claude-opus-5-5", "claude-opus-5", "claude-sonnet-5-5", "claude-fable-5-1"}


class Answerer(Protocol):
    def answer(self, utterance: str, context: Sequence[str]) -> AsyncIterator[str]:
        """Yields answer text in pieces; yields nothing if no answer is needed."""
        ...


async def drop_no_answer(chunks: AsyncIterator[str]) -> AsyncIterator[str]:
    """Passes text through unless the reply is the NONE marker.

    Holds back only the first few characters, until they show whether the
    reply starts with NONE.
    """
    head = ""
    decided = False
    async for chunk in chunks:
        if decided:
            yield chunk
            continue
        head += chunk
        stripped = head.lstrip()
        if len(stripped) < len(NO_ANSWER) and NO_ANSWER.startswith(stripped):
            continue  # could still turn out to be NONE
        if stripped.startswith(NO_ANSWER):
            return
        decided = True
        yield stripped
    if not decided and head.strip() and head.strip() != NO_ANSWER:
        yield head.strip()


def build_user_message(utterance: str, context: Sequence[str]) -> str:
    earlier = "\n".join(f"- {line}" for line in context) or "(none)"
    return f"Earlier in the conversation:\n{earlier}\n\nUtterance:\n{utterance}"


class ClaudeAnswerer:
    def __init__(self, client: anthropic.AsyncAnthropic, model: str, effort: str):
        self._client = client
        self._model = model
        self._effort = effort

    async def answer(self, utterance: str, context: Sequence[str]) -> AsyncIterator[str]:
        async for text in drop_no_answer(self._stream_text(utterance, context)):
            yield text

    async def _stream_text(self, utterance: str, context: Sequence[str]) -> AsyncIterator[str]:
        extra = {}
        if self._model in _FALLBACK_MODELS:
            # On a safety decline, the API retries on a suitable model itself.
            extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}
        async with self._client.beta.messages.stream(
            model=self._model,
            max_tokens=1024,
            # The system prompt never changes, so it is cached across calls.
            system=[{"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}],
            output_config={"effort": self._effort},
            messages=[{"role": "user", "content": build_user_message(utterance, context)}],
            **extra,
        ) as stream:
            async for text in stream.text_stream:
                yield text
