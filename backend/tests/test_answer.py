import asyncio

from app.answer import build_user_message, drop_no_answer


async def chunks(*parts):
    for part in parts:
        yield part


def collect(*parts) -> list[str]:
    async def run():
        return [text async for text in drop_no_answer(chunks(*parts))]

    return asyncio.run(run())


def test_none_reply_is_dropped():
    assert collect("NONE") == []
    assert collect("NO", "NE") == []
    assert collect(" NONE.") == []


def test_answer_passes_through_in_pieces():
    assert "".join(collect("It ", "is ", "noon.")) == "It is noon."


def test_answer_starting_like_none_is_kept():
    assert "".join(collect("NO", "! It closes at five.")) == "NO! It closes at five."
    assert "".join(collect("Nobody knows.")) == "Nobody knows."


def test_short_answer_is_kept():
    assert collect("No.") == ["No."]
    assert collect("N") == ["N"]


def test_user_message_includes_context():
    message = build_user_message("What time is it?", ["Hi there"])
    assert "- Hi there" in message
    assert message.endswith("Utterance:\nWhat time is it?")
    assert "(none)" in build_user_message("Hello?", [])
