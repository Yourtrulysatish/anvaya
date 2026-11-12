import httpx
import pytest

from anvaya.config import settings
from anvaya.llm.jsonutil import extract_json
from anvaya.llm.provider import FreeModelProvider, ProviderError

MODELS = {"data": [
    {"id": "big-model", "capabilities": ["json_mode", "tools"], "context_window": 1000, "pricing": {"input_per_1k": 0.01, "output_per_1k": 0.02}},
    {"id": "tiny-model", "capabilities": ["json_mode"], "context_window": 100, "pricing": {"input_per_1k": 0.001, "output_per_1k": 0.001}}]}


def make(handler):
    settings.freemodel_api_key = "test-key"
    p = FreeModelProvider()
    p._client = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://example.test/v1")
    p.limiter.per_minute = 1000
    return p


def test_extract_json_handles_fences_and_prose():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extract_json('Sure! Here you go: {"a": [1, {"b": "}"}]} thanks') == {"a": [1, {"b": "}"}]}
    with pytest.raises(ValueError):
        extract_json("no json here")


async def test_chat_sends_bearer_and_tracks_usage_and_cost():
    seen = {}

    def h(req: httpx.Request):
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json=MODELS)
        seen["auth"] = req.headers["authorization"]; seen["body"] = req.content
        return httpx.Response(200, json={"model": "big-model", "choices": [{"message": {"content": "hi"}, "finish_reason": "stop"}],
                                         "usage": {"prompt_tokens": 1000, "completion_tokens": 500, "completion_tokens_details": {"reasoning_tokens": 10}}})
    p = make(h)
    r = await p.chat("reasoning", [{"role": "user", "content": "x"}], model="big-model", max_tokens=100)
    assert seen["auth"] == "Bearer test-key"
    await p.list_models()
    assert p.estimate_cost("big-model", 1000, 500) == pytest.approx(0.02)
    assert r.content == "hi" and r.completion_tokens == 500
    assert b'"max_tokens":2048' in seen["body"].replace(b" ", b"")  # provider floor is 2048


async def test_retries_on_429_then_succeeds():
    calls = {"n": 0}

    def h(req):
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json=MODELS)
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, json={"error": {"message": "slow down"}}, headers={"retry-after": "0"})
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}], "usage": {}})
    p = make(h)
    p.limiter.block_for = lambda s: None
    import anvaya.llm.provider as mod
    orig = mod.asyncio.sleep
    async def fast(_): return None
    mod.asyncio.sleep = fast
    try:
        r = await p.chat("agent", [{"role": "user", "content": "x"}], model="tiny-model")
    finally:
        mod.asyncio.sleep = orig
    assert r.content == "ok" and calls["n"] == 3


@pytest.mark.parametrize("status,kind", [(401, "auth"), (402, "payment"), (400, "bad_request")])
async def test_non_retryable_errors_are_classified(status, kind):
    def h(req):
        return httpx.Response(status, json={"error": {"message": "nope"}})
    p = make(h)
    with pytest.raises(ProviderError) as e:
        await p.chat("agent", [{"role": "user", "content": "x"}], model="tiny-model")
    assert e.value.kind == kind


async def test_unknown_model_reported_accurately():
    def h(req):
        return httpx.Response(200, json=MODELS)
    p = make(h)
    p.runtime_models["agent"] = "ghost-model"
    with pytest.raises(ProviderError) as e:
        await p.resolve_model("agent")
    assert e.value.kind == "model_unavailable"
    assert (await p.check_model("ghost-model"))["available"] is False
    assert (await p.check_model("big-model"))["available"] is True


async def test_reasoning_budget_retry_when_content_empty():
    calls = []

    def h(req):
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json=MODELS)
        import json
        calls.append(json.loads(req.content)["max_tokens"])
        if len(calls) == 1:
            return httpx.Response(200, json={"choices": [{"message": {"content": ""}, "finish_reason": "length"}], "usage": {"completion_tokens": 2048}})
        return httpx.Response(200, json={"choices": [{"message": {"content": "answer"}, "finish_reason": "stop"}], "usage": {}})
    p = make(h)
    r = await p.chat("agent", [{"role": "user", "content": "x"}], model="tiny-model", max_tokens=2048)
    assert r.content == "answer" and calls == [2048, 4096]


async def test_api_key_never_in_connection_report():
    settings.freemodel_api_key = "super-secret-key"
    def h(req):
        return httpx.Response(200, json=MODELS)
    p = make(h)
    settings.freemodel_api_key = "super-secret-key"
    out = await p.test_connection(live_call=False)
    assert out["ok"] and "super-secret-key" not in str(out)


async def test_truncated_json_is_retried_with_larger_budget():
    import json
    calls = []

    def h(req):
        if req.url.path.endswith("/models"):
            return httpx.Response(200, json=MODELS)
        body = json.loads(req.content)
        calls.append(body["max_tokens"])
        if len(calls) == 1:
            return httpx.Response(200, json={"choices": [{"message": {"content": '{"a": [1, 2'}, "finish_reason": "length"}], "usage": {}})
        return httpx.Response(200, json={"choices": [{"message": {"content": '{"a": [1, 2]}'}, "finish_reason": "stop"}], "usage": {}})
    p = make(h)
    data, _ = await p.chat_json("agent", [{"role": "user", "content": "x"}], model="tiny-model", max_tokens=3000)
    assert data == {"a": [1, 2]} and calls == [3000, 6000]
