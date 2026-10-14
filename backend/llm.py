"""One way to call the model: every agent run goes through `run_agent`, which records
tokens and cost (even when the run fails) in a UsageMeter.

Prices are per 1M tokens for gpt-6-luna (OpenAI standard pricing, MGT 409 Lecture 11).
Input tokens include cached and cache-written tokens; the uncached part is the rest.
"""

from __future__ import annotations

import asyncio
import os
import time
import uuid
from contextlib import asynccontextmanager
from dataclasses import asdict, dataclass, field, replace
from decimal import Decimal
from functools import lru_cache
from typing import Any, AsyncIterator, Callable, Sequence

os.environ.setdefault("PYDANTIC_AI_NO_BANNER", "1")

import httpx  # noqa: E402
from openai import AsyncOpenAI  # noqa: E402
from pydantic_ai import Agent, capture_run_messages  # noqa: E402
from pydantic_ai.messages import ModelMessage, ModelRequest, ModelResponse, SystemPromptPart  # noqa: E402
from pydantic_ai.models.wrapper import WrapperModel  # noqa: E402
from pydantic_ai.models.openai import OpenAIResponsesModel, OpenAIResponsesModelSettings  # noqa: E402
from pydantic_ai.providers.openai import OpenAIProvider  # noqa: E402
from pydantic_ai.usage import UsageLimits  # noqa: E402

from . import config  # noqa: E402

PRICES_PER_1M = {
    "input": Decimal("0.10"),
    "cached_input": Decimal("0.01"),
    "cache_write": Decimal("0.125"),
    "output": Decimal("0.50"),
}
PRICE_SOURCE = "gpt-6-luna, OpenAI standard pricing per 1M tokens (MGT 409 Lecture 11)"


# ---- prompt caching switch (for the tokenomics experiment) --------------------------------
# gpt-6-luna caches prompt prefixes automatically and cannot be told not to. To measure
# "caching off", every model request gets a unique random string at the very start of its
# instructions and as an opening system message, so no request shares a prefix with any
# other and nothing can be read from the cache. (Cache writes may still be billed; the
# experiment records them.)
_prompt_cache_enabled = True


def set_prompt_cache(enabled: bool) -> None:
    global _prompt_cache_enabled
    _prompt_cache_enabled = enabled


def _with_nonce(messages: list[ModelMessage], params: Any) -> tuple[list[ModelMessage], Any]:
    """Put a fresh random string at the start of the instructions (where PydanticAI sends
    them: the request parameters' instruction parts, and the message field as a fallback)."""
    nonce = f"[request {uuid.uuid4().hex}]\n"
    parts = list(getattr(params, "instruction_parts", None) or [])
    if parts:
        parts[0] = replace(parts[0], content=nonce + parts[0].content)
        params = replace(params, instruction_parts=parts)
    messages = [replace(m, instructions=nonce + m.instructions) if isinstance(m, ModelRequest) and m.instructions else m
                for m in messages]
    # The provider does not seem to count the separate instructions field as part of the
    # cached prefix, so the same string also opens the input as a system message.
    for i, m in enumerate(messages):
        if isinstance(m, ModelRequest):
            messages[i] = replace(m, parts=[SystemPromptPart(content=nonce.strip()), *m.parts])
            break
    return messages, params


# Responses thrown away because they still came back with cached tokens (see below), and how
# many responses the gateway reported as retried. The experiment reports both.
NO_CACHE_DISCARDED: list[dict[str, Any]] = []
GATEWAY_RETRIES = {"responses": 0, "retried": 0}


class NoPromptCacheModel(WrapperModel):
    """Every attempt gets a fresh random string.

    Retries happen here, not in the HTTP client: a client retry re-sends the identical
    request, and the provider has often already cached the first attempt. The gateway can
    also retry a slow request upstream on its own (byte for byte), which we cannot switch
    off per request; if a response still reports cached tokens, it is discarded (its cost
    recorded in NO_CACHE_DISCARDED) and the request is asked again with a new string."""

    async def request(self, messages, model_settings, model_request_parameters):  # type: ignore[override]
        reasks = 0
        for attempt in range(5):
            fresh_messages, params = _with_nonce(messages, model_request_parameters)
            try:
                response = await super().request(fresh_messages, model_settings, params)
            except Exception as exc:
                if attempt == 4 or not _transient(exc):
                    raise
                await asyncio.sleep(1.5 * (attempt + 1))
                continue
            u = response.usage
            if u.cache_read_tokens and reasks < 2:
                reasks += 1
                NO_CACHE_DISCARDED.append({"input_tokens": u.input_tokens, "cached_input_tokens": u.cache_read_tokens,
                                           "cache_write_tokens": u.cache_write_tokens, "output_tokens": u.output_tokens,
                                           "cost_usd": cost_usd(u.input_tokens, u.cache_read_tokens, u.cache_write_tokens, u.output_tokens)})
                continue
            return response
        raise RuntimeError("unreachable")

    @asynccontextmanager
    async def request_stream(self, messages, model_settings, model_request_parameters, run_context=None) -> AsyncIterator[Any]:  # type: ignore[override]
        messages, params = _with_nonce(messages, model_request_parameters)
        async with super().request_stream(messages, model_settings, params, run_context) as s:
            yield s


def _transient(exc: Exception) -> bool:
    text = f"{type(exc).__name__} {exc}"
    return any(k in text for k in ("Timeout", "timed out", "Connection", "status_code: 5", "status_code: 429", "RateLimit"))


@lru_cache(maxsize=1)
def _base_model() -> OpenAIResponsesModel:
    return OpenAIResponsesModel(config.MODEL_ID, provider=OpenAIProvider(openai_client=config.async_client()))


async def _count_gateway_retry(response: httpx.Response) -> None:
    GATEWAY_RETRIES["responses"] += 1
    if response.headers.get("x-portkey-retry-attempt-count", "0").strip() not in ("", "0", "-1"):
        GATEWAY_RETRIES["retried"] += 1


@lru_cache(maxsize=1)
def _base_model_no_client_retries() -> OpenAIResponsesModel:
    client = AsyncOpenAI(api_key=config._api_key(), base_url=config.PORTKEY_BASE_URL, timeout=60, max_retries=0,
                         http_client=httpx.AsyncClient(timeout=60, event_hooks={"response": [_count_gateway_retry]}))
    return OpenAIResponsesModel(config.MODEL_ID, provider=OpenAIProvider(openai_client=client))


def model():
    return _base_model() if _prompt_cache_enabled else NoPromptCacheModel(_base_model_no_client_retries())


def settings(max_tokens: int, effort: str = "none", trace_id: str | None = None) -> OpenAIResponsesModelSettings:
    """Per-call settings. Portkey's response cache is bypassed so every number is a real
    model call; the app keeps its own per-document cache instead (see intake.py)."""
    headers = {"x-portkey-cache-force-refresh": "true"}
    if trace_id:
        headers["x-portkey-trace-id"] = trace_id
    return OpenAIResponsesModelSettings(
        max_tokens=max_tokens, openai_reasoning_effort=effort, extra_headers=headers  # type: ignore[typeddict-item]
    )


def cost_usd(input_tokens: int, cached: int, written: int, output_tokens: int) -> float:
    m = Decimal(1_000_000)
    uncached = max(input_tokens - cached - written, 0)
    total = (
        uncached / m * PRICES_PER_1M["input"]
        + cached / m * PRICES_PER_1M["cached_input"]
        + written / m * PRICES_PER_1M["cache_write"]
        + output_tokens / m * PRICES_PER_1M["output"]
    )
    return float(total)


@dataclass
class CallRecord:
    agent: str
    label: str
    requests: int
    input_tokens: int
    cached_input_tokens: int
    cache_write_tokens: int
    output_tokens: int
    reasoning_tokens: int
    seconds: float
    cost_usd: float
    ok: bool
    error: str | None = None
    from_cache: bool = False
    member: str | None = None   # which panel member the call belongs to (for the per-doctor meter)


@dataclass
class UsageMeter:
    calls: list[CallRecord] = field(default_factory=list)
    listeners: list[Callable[[CallRecord], None]] = field(default_factory=list)

    member_of: Callable[[str, str], str] | None = None  # (agent, label) -> panel member

    def add(self, record: CallRecord) -> None:
        if record.member is None and self.member_of:
            record.member = self.member_of(record.agent, record.label)
        self.calls.append(record)
        for listener in self.listeners:
            listener(record)

    def add_cached(self, agent: str, label: str) -> None:
        self.add(CallRecord(agent, label, 0, 0, 0, 0, 0, 0, 0.0, 0.0, True, from_cache=True))

    def totals(self) -> dict[str, Any]:
        live = [c for c in self.calls if not c.from_cache]
        keys = ("requests", "input_tokens", "cached_input_tokens", "cache_write_tokens", "output_tokens", "reasoning_tokens")
        out: dict[str, Any] = {k: sum(getattr(c, k) for c in live) for k in keys}
        out["cost_usd"] = round(sum(c.cost_usd for c in live), 6)
        out["model_calls"] = len(live)
        out["cache_hits"] = len(self.calls) - len(live)
        out["failed_calls"] = sum(1 for c in live if not c.ok)
        return out

    def by_member(self) -> dict[str, dict[str, Any]]:
        groups: dict[str, dict[str, Any]] = {}
        for c in self.calls:
            if c.from_cache:
                continue
            g = groups.setdefault(c.member or c.agent, {"calls": 0, "input_tokens": 0, "cached_input_tokens": 0,
                                                       "cache_write_tokens": 0, "output_tokens": 0, "cost_usd": 0.0, "seconds": 0.0})
            g["calls"] += 1
            for k in ("input_tokens", "cached_input_tokens", "cache_write_tokens", "output_tokens"):
                g[k] += getattr(c, k)
            g["cost_usd"] = round(g["cost_usd"] + c.cost_usd, 6)
            g["seconds"] = round(g["seconds"] + c.seconds, 2)
        return groups

    def by_agent(self) -> dict[str, dict[str, Any]]:
        groups: dict[str, dict[str, Any]] = {}
        for c in self.calls:
            if c.from_cache:
                continue
            g = groups.setdefault(c.agent, {"calls": 0, "input_tokens": 0, "cached_input_tokens": 0, "output_tokens": 0, "cost_usd": 0.0})
            g["calls"] += 1
            g["input_tokens"] += c.input_tokens
            g["cached_input_tokens"] += c.cached_input_tokens
            g["output_tokens"] += c.output_tokens
            g["cost_usd"] = round(g["cost_usd"] + c.cost_usd, 6)
        return groups

    def as_dict(self) -> dict[str, Any]:
        return {"price_source": PRICE_SOURCE, "prices_per_1m": {k: float(v) for k, v in PRICES_PER_1M.items()},
                "prompt_cache": _prompt_cache_enabled, "totals": self.totals(), "by_agent": self.by_agent(),
                "by_member": self.by_member(), "calls": [asdict(c) for c in self.calls]}


def _usage_from(messages: Sequence[Any]) -> tuple[int, int, int, int, int, int]:
    req = inp = cached = written = out = reasoning = 0
    for m in messages:
        if isinstance(m, ModelResponse):
            u = m.usage
            req += 1
            inp += u.input_tokens
            cached += u.cache_read_tokens
            written += u.cache_write_tokens
            out += u.output_tokens
            reasoning += int((u.details or {}).get("reasoning_tokens", 0))
    return req, inp, cached, written, out, reasoning


async def run_agent(
    agent: Agent[Any, Any],
    prompt: str | Sequence[Any],
    *,
    meter: UsageMeter,
    agent_name: str,
    label: str,
    model_settings: OpenAIResponsesModelSettings,
    request_limit: int = 3,
    deps: Any = None,
) -> Any:
    """Run one agent and record its usage. Re-raises errors after recording them."""
    from .traps import current_agent  # local import: traps is optional instrumentation
    token = current_agent.set(label)
    started = time.perf_counter()
    with capture_run_messages() as messages:
        try:
            result = await agent.run(
                prompt, model_settings=model_settings, usage_limits=UsageLimits(request_limit=request_limit),
                deps=deps,
            )
            ok, error = True, None
        except Exception as exc:
            ok, error, result = False, f"{type(exc).__name__}: {str(exc)[:300]}", None
        req, inp, cached, written, out, reasoning = _usage_from(messages)
    meter.add(CallRecord(
        agent_name, label, req, inp, cached, written, out, reasoning,
        round(time.perf_counter() - started, 2), cost_usd(inp, cached, written, out), ok, error,
    ))
    current_agent.reset(token)
    if result is None:
        raise RuntimeError(f"{agent_name} failed on {label}: {error}")
    return result.output
