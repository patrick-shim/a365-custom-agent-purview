import asyncio
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest

from agent import ProtectedAgent, PolicyBlocked, AgentError
from purview import PolicyDecision, PurviewError
from onedrive import Document


def decision(allowed=True, inline=True):
    return PolicyDecision(allowed, not allowed, "test", "uploadText", "correlation", True, inline)


def fixture():
    user = NS(oid="user")
    auth = NS(graph_token=AsyncMock(return_value="token"))
    drive = NS(read_text=AsyncMock(return_value=Document("SECRET_IN_FILE", {"id": "item"})))
    policy = NS(evaluate=AsyncMock(return_value=decision()))
    foundry = NS(respond=AsyncMock(return_value=NS(status="completed", output=[], output_text="Clean summary")))
    return user, ProtectedAgent(NS(), auth, drive, policy, foundry)


def run(awaitable):
    return asyncio.run(awaitable)


def test_denied_file_never_reaches_model():
    user, agent = fixture()
    async def evaluate(text, *args, stage, **kwargs):
        return decision(stage != "file")
    agent.purview.evaluate.side_effect = evaluate
    with pytest.raises(PolicyBlocked):
        run(agent.chat(user, "Summarize", "test.txt"))
    agent.foundry.respond.assert_not_called()


def test_inspection_failure_never_reaches_model():
    user, agent = fixture()
    async def evaluate(text, *args, stage, **kwargs):
        if stage == "file":
            raise PurviewError("incomplete", "No verdict")
        return decision()
    agent.purview.evaluate.side_effect = evaluate
    with pytest.raises(PurviewError):
        run(agent.chat(user, "Summarize", "test.txt"))
    agent.foundry.respond.assert_not_called()


def test_prompt_denial_does_not_fetch_file():
    user, agent = fixture()
    agent.purview.evaluate.return_value = decision(False)
    with pytest.raises(PolicyBlocked):
        run(agent.chat(user, "Prompt", "test.txt"))
    agent.onedrive.read_text.assert_not_called()
    agent.foundry.respond.assert_not_called()


def test_file_passes_before_foundry_sees_it_and_history_unchanged():
    user, agent = fixture()
    order = []
    async def evaluate(text, *args, stage, **kwargs):
        order.append(stage)
        return decision()
    async def respond(messages):
        assert "file" in order
        assert "SECRET_IN_FILE" in str(messages)
        order.append("model")
        return NS(status="completed", output=[], output_text="Clean summary")
    agent.purview.evaluate.side_effect = evaluate
    agent.foundry.respond.side_effect = respond
    history = [{"role": "user", "content": "old message"}]
    result = run(agent.chat(user, "Summarize", "test.txt", history))
    assert result.text == "Clean summary"
    assert order.index("file") < order.index("model") < order.index("response")
    assert history == [{"role": "user", "content": "old message"}]


def test_final_context_guard_can_prevent_model_call():
    user, agent = fixture()
    async def evaluate(text, *args, stage, **kwargs):
        # Individual document allowed, aggregate context policy denies.
        return decision(not (stage == "prompt" and "SECRET_IN_FILE" in text))
    agent.purview.evaluate.side_effect = evaluate
    with pytest.raises(PolicyBlocked):
        run(agent.chat(user, "Summarize", "test.txt"))
    agent.foundry.respond.assert_not_called()


def test_response_denial_withholds_reply_without_false_pre_model_claim():
    user, agent = fixture()
    async def evaluate(text, *args, stage, **kwargs):
        return decision(stage != "response")
    agent.purview.evaluate.side_effect = evaluate
    with pytest.raises(PolicyBlocked, match="withheld") as error:
        run(agent.chat(user, "Hello"))
    assert "not sent to the model" not in str(error.value)


def test_audit_only_response_is_reported_as_such():
    user, agent = fixture()
    async def evaluate(text, *args, stage, **kwargs):
        return decision(inline=stage != "response")
    agent.purview.evaluate.side_effect = evaluate
    assert not run(agent.chat(user, "Hello")).output_inline_evaluated


def test_denied_tool_file_stops_before_second_model_call():
    user, agent = fixture()
    call = NS(type="function_call", name="read_onedrive_file", arguments='{"path":"test.txt"}')
    agent.foundry.respond.return_value = NS(status="completed", output=[call])
    async def evaluate(text, *args, stage, **kwargs):
        return decision(stage != "file")
    agent.purview.evaluate.side_effect = evaluate
    with pytest.raises(PolicyBlocked):
        run(agent.chat(user, "Summarize test.txt"))
    assert agent.foundry.respond.await_count == 1


def test_incomplete_model_response_is_never_released():
    user, agent = fixture()
    agent.foundry.respond.return_value = NS(status="incomplete")
    with pytest.raises(AgentError, match="incomplete"):
        run(agent.chat(user, "Hello"))
