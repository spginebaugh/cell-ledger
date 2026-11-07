"""What both steps share about calling Claude: the turn runner, request parameters, and how a
finished turn is read."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol

import anthropic
from anthropic.lib._parse._transform import to_json_output_format
from anthropic.types.beta import BetaMessage
from pydantic import BaseModel

Event = dict[str, Any]
"""One streamed event; the shapes are documented in ``cell_ledger_api.routes.agent``."""

Emit = Callable[[Event], Awaitable[None]]

MAX_TURNS = 8
MAX_TOKENS = 16000
DEFAULT_MODEL = "claude-opus-5-5"
DEFAULT_EFFORT = "medium"
NOT_CONFIGURED = "Claude is not configured (CELL_LEDGER_ANTHROPIC_API_KEY)"


class AgentUnavailable(RuntimeError):
    """Claude could not produce a usable answer: not configured, declined, or unreadable."""


class TurnRunner(Protocol):
    """One request to Claude: stream it, forward thinking to ``emit``, return the message."""

    async def __call__(self, params: dict[str, Any], emit: Emit) -> BetaMessage: ...


def sdk_turn_runner(client: anthropic.AsyncAnthropic) -> TurnRunner:
    async def run(params: dict[str, Any], emit: Emit) -> BetaMessage:
        async with client.beta.messages.stream(**params) as stream:
            async for event in stream:
                if (
                    event.type == "content_block_delta"
                    and event.delta.type == "thinking_delta"
                    and event.delta.thinking
                ):
                    await emit({"type": "thinking", "delta": event.delta.thinking})
            return await stream.get_final_message()

    return run


async def quiet(_: Event) -> None:
    """An ``Emit`` for callers with no browser attached."""


def request_params(
    *,
    model: str,
    effort: str,
    system: str,
    output: type[BaseModel],
    tools: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Everything but ``messages`` for one step's requests; Claude's final answer is held to
    the JSON schema of ``output``."""
    params: dict[str, Any] = {
        "model": model,
        "max_tokens": MAX_TOKENS,
        "thinking": {"type": "adaptive", "display": "summarized"},
        "output_config": {"effort": effort, "format": to_json_output_format(output)},
        # Safety classifiers can misfire on biomedical text; a decline re-runs the request on
        # Anthropic's recommended substitute instead of failing the user.
        "betas": ["server-side-fallback-2026-07-01"],
        "fallbacks": "default",
        "system": system,
    }
    if tools:
        params["tools"] = tools
    return params


def reject_refusal(message: BetaMessage) -> None:
    if message.stop_reason == "refusal":
        raise AgentUnavailable("the model declined this request")


def final_text(message: BetaMessage) -> str:
    """The text blocks of a turn, joined: with structured output, the JSON answer."""
    return "".join(b.text for b in message.content if b.type == "text")
