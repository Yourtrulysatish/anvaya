"""FreeModel.in provider adapter.

Verified against the live service (2026-11-12), not assumed:
  * Base URL  https://freemodel.in/v1 , auth `Authorization: Bearer <key>`
  * GET /models  -> OpenAI-style list enriched with context_window, capabilities[], pricing{input_per_1k,output_per_1k}
  * POST /chat/completions -> OpenAI-style; `max_tokens` < 2048 is raised to 2048 server-side; reasoning models spend
    tokens on hidden reasoning (usage.completion_tokens_details.reasoning_tokens)
  * `response_format: {"type":"json_object"}` is accepted but output may still arrive inside ``` fences
  * Rate limit headers: x-ratelimit-limit (requests/min), x-ratelimit-remaining, x-ratelimit-reset (epoch),
    x-ratelimit-limit-tokens / x-ratelimit-remaining-tokens. HTTP 402 = empty balance.
"""
from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx

from ..config import TASKS, settings
from ..db import get_store
from .jsonutil import extract_json


class ProviderError(Exception):
    def __init__(self, kind: str, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.kind, self.status = kind, status

    def to_dict(self):
        return {"kind": self.kind, "message": str(self), "status": self.status}


@dataclass
class ChatResult:
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    cost_usd: Optional[float] = None
    finish_reason: str = ""
    latency_ms: int = 0


class RateLimiter:
    """Sliding-window limiter, sized below the provider's published 60 req/min."""
    def __init__(self, per_minute: int):
        self.per_minute = max(1, per_minute)
        self.stamps: list[float] = []
        self.blocked_until = 0.0
        self.lock = asyncio.Lock()

    async def acquire(self):
        async with self.lock:
            while True:
                now = time.monotonic()
                self.stamps = [t for t in self.stamps if now - t < 60]
                wait = max(self.blocked_until - now, 0.0)
                if len(self.stamps) >= self.per_minute:
                    wait = max(wait, 60 - (now - self.stamps[0]) + 0.05)
                if wait <= 0:
                    self.stamps.append(now)
                    return
                await asyncio.sleep(min(wait, 5))

    def block_for(self, seconds: float):
        self.blocked_until = max(self.blocked_until, time.monotonic() + seconds)


# Preference hints used only when a task has no explicit model. They are matched against the *live* catalogue;
# nothing here is assumed to exist.
_PREFER = {
    # strong-but-economical defaults; premium models (e.g. Opus) can be chosen explicitly in Settings
    "reasoning": ["sonnet-5-5", "gemini-3.1-pro", "kimi-k3", "opus-5-5", "gpt-6"],
    "report": ["sonnet-5-5", "gemini-3.1-pro", "opus-5-5", "gpt-6"],
    "agent": ["gemini-3.7-flash", "deepseek-v4.1-flash", "glm-5.3-flash", "deepseek-v4-flash"],
    "extraction": ["gemini-3.7-flash", "deepseek-v4.1-flash", "glm-5.3-flash", "qwen3.7-max"],
    "summarisation": ["glm-5.3-flash", "deepseek-v4.1-flash", "gemini-3.7-flash"],
}


class FreeModelProvider:
    def __init__(self):
        self.limiter = RateLimiter(settings.requests_per_minute)
        self._client: Optional[httpx.AsyncClient] = None
        self._catalog: list[dict] = []
        self._catalog_at = 0.0
        self.last_rate_headers: dict = {}
        self.runtime_models: dict = {}   # set from the Settings UI (persisted by the API layer)
        self.session_usage = {"prompt": 0, "completion": 0, "cost": 0.0, "calls": 0, "errors": 0}

    # ---------------------------------------------------------------- plumbing
    def _http(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=settings.freemodel_base_url, timeout=httpx.Timeout(120, connect=15))
        return self._client

    def _headers(self) -> dict:
        if not settings.freemodel_api_key:
            raise ProviderError("not_configured", "FREEMODEL_API_KEY is not set on the backend.")
        return {"Authorization": f"Bearer {settings.freemodel_api_key}", "Content-Type": "application/json"}

    def _note_headers(self, r: httpx.Response):
        keep = {k: v for k, v in r.headers.items() if k.lower().startswith("x-ratelimit")}
        if keep:
            self.last_rate_headers = keep

    # ---------------------------------------------------------------- catalogue
    async def list_models(self, force: bool = False) -> list[dict]:
        if self._catalog and not force and time.time() - self._catalog_at < 300:
            return self._catalog
        try:
            r = await self._http().get("/models", headers=self._headers())
        except httpx.HTTPError as e:
            raise ProviderError("network", f"Could not reach FreeModel: {e.__class__.__name__}") from e
        self._note_headers(r)
        self._raise_for_status(r)
        self._catalog = r.json().get("data", [])
        self._catalog_at = time.time()
        return self._catalog

    def model_info(self, model_id: str) -> Optional[dict]:
        return next((m for m in self._catalog if m["id"] == model_id), None)

    def estimate_cost(self, model_id: str, pt: int, ct: int) -> Optional[float]:
        m = self.model_info(model_id)
        p = (m or {}).get("pricing") or {}
        if "input_per_1k" not in p:
            return None
        return pt / 1000 * p["input_per_1k"] + ct / 1000 * p.get("output_per_1k", p["input_per_1k"])

    async def resolve_model(self, task: str) -> str:
        assert task in TASKS, task
        explicit = self.runtime_models.get(task) or settings.model_overrides.get(task)
        catalog = await self.list_models()
        ids = {m["id"] for m in catalog}
        if explicit:
            if explicit not in ids:
                raise ProviderError("model_unavailable", f"Configured model '{explicit}' for task '{task}' is not in the FreeModel catalogue.")
            return explicit
        usable = [m for m in catalog if "json_mode" in m.get("capabilities", [])]
        for hint in _PREFER[task]:
            for m in usable:
                if hint in m["id"]:
                    return m["id"]
        if not usable:
            raise ProviderError("model_unavailable", "No JSON-capable chat model in the FreeModel catalogue.")
        key = lambda m: (m.get("pricing") or {}).get("output_per_1k", 9)
        return sorted(usable, key=key)[0]["id"]

    async def check_model(self, model_id: str) -> dict:
        catalog = await self.list_models()
        m = next((x for x in catalog if x["id"] == model_id), None)
        if not m:
            return {"id": model_id, "available": False, "reason": "not listed in the FreeModel catalogue"}
        return {"id": model_id, "available": True, "context_window": m.get("context_window"),
                "capabilities": m.get("capabilities"), "pricing": m.get("pricing")}

    async def test_connection(self, live_call: bool = True) -> dict:
        out: dict[str, Any] = {"configured": settings.llm_configured, "base_url": settings.freemodel_base_url}
        if not settings.llm_configured:
            out.update(ok=False, error="FREEMODEL_API_KEY is not set on the backend.")
            return out
        try:
            cat = await self.list_models(force=True)
            out.update(ok=True, models=len(cat), rate_limit=self.last_rate_headers)
            if live_call:
                model = await self.resolve_model("summarisation")
                t0 = time.time()
                res = await self.chat("summarisation", [{"role": "user", "content": "Reply with the single word: ready"}], max_tokens=2048, temperature=0)
                out.update(test_model=model, test_reply=res.content.strip()[:40], latency_ms=int((time.time() - t0) * 1000))
        except ProviderError as e:
            out.update(ok=False, error=e.to_dict())
        return out

    # ---------------------------------------------------------------- chat
    def _raise_for_status(self, r: httpx.Response):
        if r.status_code < 400:
            return
        try:
            detail = r.json().get("error", {})
            msg = detail.get("message") if isinstance(detail, dict) else str(detail)
        except Exception:
            msg = r.text[:200]
        msg = msg or f"HTTP {r.status_code}"
        if r.status_code in (401, 403):
            raise ProviderError("auth", f"Authentication failed: {msg}", r.status_code)
        if r.status_code == 402:
            raise ProviderError("payment", "FreeModel balance is empty (HTTP 402).", 402)
        if r.status_code == 429:
            raise ProviderError("rate_limit", msg, 429)
        if r.status_code in (400, 404) and re.search(r"model.{0,40}(not found|does not exist|unknown|unavailable|not supported|invalid)|(unknown|invalid|no such) model", msg or "", re.I):
            raise ProviderError("model_unavailable", msg, r.status_code)
        if r.status_code >= 500:
            raise ProviderError("server", msg, r.status_code)
        raise ProviderError("bad_request", msg, r.status_code)

    async def chat(self, task: str, messages: list[dict], *, model: str = None, json_mode: bool = False,
                   temperature: float = 0.7, max_tokens: int = 4096, project_id: str = None,
                   retries: int = 4) -> ChatResult:
        model = model or await self.resolve_model(task)
        body = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max(2048, max_tokens)}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        delay, last_err = 2.0, None
        for attempt in range(retries + 1):
            await self.limiter.acquire()
            t0 = time.time()
            try:
                r = await self._http().post("/chat/completions", json=body, headers=self._headers())
                self._note_headers(r)
                if r.status_code == 429:
                    reset = r.headers.get("x-ratelimit-reset")
                    wait = r.headers.get("retry-after")
                    secs = float(wait) if wait else (max(float(reset) - time.time(), 1) if reset else delay)
                    self.limiter.block_for(min(secs, 60))
                self._raise_for_status(r)
                data = r.json()
                choice = (data.get("choices") or [{}])[0]
                content = (choice.get("message") or {}).get("content") or ""
                usage = data.get("usage") or {}
                pt, ct = usage.get("prompt_tokens", 0), usage.get("completion_tokens", 0)
                rt = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens", 0)
                truncated = choice.get("finish_reason") == "length" and (not content.strip() or json_mode)
                if truncated and body["max_tokens"] < 16000:
                    # reasoning consumed the budget (documented) or JSON was cut off mid-way -> retry with more room
                    body["max_tokens"] = min(16000, body["max_tokens"] * 2)
                    self._account(project_id, task, model, pt, ct)
                    continue
                cost = self._account(project_id, task, model, pt, ct)
                return ChatResult(content, data.get("model", model), pt, ct, rt, cost, choice.get("finish_reason", ""), int((time.time() - t0) * 1000))
            except ProviderError as e:
                last_err = e
                self.session_usage["errors"] += 1
                if e.kind in ("auth", "payment", "model_unavailable", "bad_request", "not_configured"):
                    raise
            except (httpx.TimeoutException, httpx.TransportError) as e:
                self.session_usage["errors"] += 1
                last_err = ProviderError("timeout" if isinstance(e, httpx.TimeoutException) else "network", f"{e.__class__.__name__} talking to FreeModel")
            except ValueError as e:
                last_err = ProviderError("bad_response", f"Malformed response from FreeModel: {e}")
            if attempt < retries:
                await asyncio.sleep(delay)
                delay = min(delay * 2, 30)
        raise last_err or ProviderError("unknown", "request failed")

    def _account(self, project_id, task, model, pt, ct) -> Optional[float]:
        cost = self.estimate_cost(model, pt, ct)
        s = self.session_usage
        s["prompt"] += pt; s["completion"] += ct; s["calls"] += 1; s["cost"] += cost or 0
        try:
            get_store().log_usage(project_id, task, model, pt, ct, cost or 0)
        except Exception:
            pass
        return cost

    async def chat_json(self, task: str, messages: list[dict], *, schema_hint: str = "", **kw):
        """Chat expecting JSON. One repair attempt if parsing fails."""
        msgs = list(messages)
        if schema_hint:
            msgs = msgs + [{"role": "user", "content": f"Respond with a single valid JSON value only. {schema_hint}"}]
        res = await self.chat(task, msgs, json_mode=True, **kw)
        try:
            return extract_json(res.content), res
        except ValueError:
            fix = msgs + [{"role": "assistant", "content": res.content[:3000]},
                          {"role": "user", "content": "That was not valid JSON. Return only the corrected JSON, no prose."}]
            res2 = await self.chat(task, fix, json_mode=True, **kw)
            return extract_json(res2.content), res2


provider = FreeModelProvider()
