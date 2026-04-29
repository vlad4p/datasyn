"""LiteLLM proxy chat - OpenAI-compatible client (same pattern as Datacyber-core ``litellm_client.get_chat_model``).
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

import httpx
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_openai import ChatOpenAI

from agent.config import settings

logger = logging.getLogger(__name__)


def running_in_docker() -> bool:
    return os.path.exists("/.dockerenv")


def parse_litellm_proxy_error_payload(data: dict[str, Any]) -> dict[str, Any] | None:
    """Detect LiteLLM proxy failure envelopes or OpenAI-style ``{"error": {...}}`` bodies."""
    if not isinstance(data, dict):
        return None
    if data.get("status") == "failure" or (
        "user_api_key" in data and isinstance(data.get("error_information"), dict)
    ):
        ei = data["error_information"] if isinstance(data.get("error_information"), dict) else {}
        return {
            "kind": "litellm_proxy_failure",
            "user_api_key_hash": data.get("user_api_key"),
            "error_code": ei.get("error_code"),
            "error_class": ei.get("error_class"),
            "error_message": (ei.get("error_message") or "").strip() or None,
        }
    err = data.get("error")
    if isinstance(err, dict):
        return {
            "kind": "openai_compatible_error",
            "message": err.get("message"),
            "code": err.get("code"),
            "param": err.get("param"),
            "type": err.get("type"),
        }
    return None


def parse_litellm_proxy_response_body(text: str) -> dict[str, Any] | None:
    if not text or not text.strip().startswith("{"):
        return None
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    return parse_litellm_proxy_error_payload(data) if isinstance(data, dict) else None


def _is_litellm_model_not_found(parsed: dict[str, Any]) -> bool:
    """True when CHAT_MODEL is not registered for this proxy key / team."""
    cls = (parsed.get("error_class") or "").strip()
    msg = f"{parsed.get('error_message') or ''} {parsed.get('message') or ''}".lower()
    if cls == "ProxyModelNotFoundError":
        return True
    return "invalid model name" in msg or "modelnotfound" in msg.replace(" ", "")


def _hint_litellm_upstream_provider_key(parsed: dict[str, Any]) -> str | None:
    """LLM provider key invalid on the LiteLLM host (not the brain's LITELLM_KEY)."""
    msg = f"{parsed.get('error_message') or ''} {parsed.get('message') or ''}"
    lower = msg.lower()
    compact = lower.replace(" ", "")
    gemini = "gemini" in lower or "generativelanguage" in lower
    if gemini and (
        "api_key_invalid" in compact
        or "api key not valid" in lower
        or ("authenticationerror" in compact and "geminiexception" in compact)
    ):
        return (
            "Google Gemini rejected the API key that **LiteLLM** uses for this model — not the brain's "
            "LITELLM_KEY. On the **LiteLLM server** host, set a valid Gemini key (e.g. GEMINI_API_KEY or "
            "`api_key` on that model in `model_list`), restart the proxy, and confirm the key in Google AI Studio / "
            "Cloud console is allowed for the Generative Language API."
        )
    return None


def hint_for_litellm_parsed_error(parsed: dict[str, Any]) -> str:
    if parsed.get("kind") == "litellm_proxy_failure":
        if _is_litellm_model_not_found(parsed):
            return (
                "LiteLLM does not expose this model id for your virtual key (CHAT_MODEL mismatch). "
                "Fix: open GET /health/llm on the brain or call the proxy GET /v1/models with the same Bearer key; "
                "set CHAT_MODEL in .env to an exact returned `id`, or add the alias in the proxy `model_list` / "
                "key permissions for that team."
            )
        prov = _hint_litellm_upstream_provider_key(parsed)
        if prov:
            return prov
        h = parsed.get("user_api_key_hash")
        code = parsed.get("error_code")
        return (
            "LiteLLM proxy rejected the API key (Bearer token). "
            f"The proxy recorded key hash {h!r} (compare with its logs). "
            "Fix: register a virtual key in the LiteLLM admin UI / LiteLLM_VerificationTokenTable, "
            "or set LITELLM_KEY on the brain to the proxy's LITELLM_MASTER_KEY if your deployment uses that. "
            "After editing .env, run: docker compose up -d --force-recreate brain. "
            f"Proxy error_code={code!r}."
        )
    if parsed.get("kind") == "openai_compatible_error":
        if _is_litellm_model_not_found(parsed):
            return (
                "LiteLLM / upstream rejected the model id (CHAT_MODEL). "
                "Use GET /health/llm or proxy GET /v1/models and set CHAT_MODEL to a listed `id`. "
                f"Detail: {parsed.get('message') or parsed} "
                f"(code={parsed.get('code')!r})."
            )
        prov = _hint_litellm_upstream_provider_key(parsed)
        if prov:
            return prov
        return (
            f"Upstream returned: {parsed.get('message') or parsed} "
            f"(code={parsed.get('code')!r}, type={parsed.get('type')!r})."
        )
    return ""


def _collect_http_bodies_from_exception(exc: BaseException) -> list[str]:
    """Pull raw JSON/text bodies from OpenAI/LangChain/httpx exception chains."""
    out: list[str] = []
    seen: set[int] = set()

    def visit(e: BaseException | None) -> None:
        if e is None or id(e) in seen:
            return
        seen.add(id(e))
        body = getattr(e, "body", None)
        if isinstance(body, str) and body.strip():
            out.append(body)
        resp = getattr(e, "response", None)
        if resp is not None:
            t = getattr(resp, "text", None)
            if isinstance(t, str) and t.strip():
                out.append(t)
        for a in getattr(e, "args", ()):
            if isinstance(a, str) and "{" in a:
                out.append(a)
        cause: BaseException | None = None
        c = getattr(e, "__cause__", None)
        if isinstance(c, BaseException):
            cause = c
            visit(cause)
        ctx = getattr(e, "__context__", None)
        if isinstance(ctx, BaseException) and ctx is not cause:
            visit(ctx)
        subs = getattr(e, "exceptions", None)
        if subs:
            for sub in subs:
                if isinstance(sub, BaseException):
                    visit(sub)

    visit(exc)
    return out


def explain_litellm_http_exception(exc: BaseException) -> str | None:
    """If ``exc`` wraps a LiteLLM proxy auth/HTTP body, return a short user-facing hint."""
    bodies = _collect_http_bodies_from_exception(exc)
    for raw in bodies:
        parsed = parse_litellm_proxy_response_body(raw)
        if parsed:
            return hint_for_litellm_parsed_error(parsed)
    # Fallback: JSON object embedded in the stringified exception
    blob = str(exc)
    for m in re.finditer(r"\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\}", blob):
        parsed = parse_litellm_proxy_response_body(m.group(0))
        if parsed:
            return hint_for_litellm_parsed_error(parsed)
    return None


async def probe_litellm_proxy() -> dict[str, Any]:
    """GET OpenAI-compatible ``/v1/models``; use ``GET /health/llm`` to debug connection from this process."""
    base = settings.litellm_api_base
    key = settings.litellm_key
    out: dict[str, Any] = {
        "in_docker": running_in_docker(),
        "litellm_base": base,
        "has_key": bool(key),
    }
    if not base or not key:
        out["ok"] = False
        out["error"] = "Set LITELLM_PROXY_BASE (or LITELLM_API_BASE) and LITELLM_KEY (or LITELLM_PROXY_KEY)."
        return out
    url = f"{base.rstrip('/')}/models"
    try:
        t = httpx.Timeout(8.0, connect=4.0)
        async with httpx.AsyncClient(timeout=t, trust_env=False) as client:
            r = await client.get(url, headers={"Authorization": f"Bearer {key}"})
        out["status_code"] = r.status_code
        out["ok"] = 200 <= r.status_code < 300
        if not out["ok"]:
            text = r.text or ""
            out["body_preview"] = text[:800]
            parsed = parse_litellm_proxy_response_body(text)
            if parsed:
                out["litellm_error_parsed"] = parsed
                out["hint"] = hint_for_litellm_parsed_error(parsed)
    except Exception as exc:
        out["ok"] = False
        out["error"] = str(exc)[:500]
    return out


def _request_timeout() -> float:
    raw = os.getenv("LITELLM_REQUEST_TIMEOUT", "300")
    try:
        return float(raw)
    except ValueError:
        return 300.0


def _temperature() -> float:
    raw = os.getenv("LITELLM_TEMPERATURE", "0.2")
    try:
        return float(raw)
    except ValueError:
        return 0.2


def build_chat_model() -> BaseChatModel:
    """Return a LangChain chat model that talks only to the LiteLLM OpenAI-compatible proxy."""
    if not settings.litellm_key:
        raise RuntimeError(
            "Set LITELLM_KEY or LITELLM_PROXY_KEY to your LiteLLM proxy API key."
        )
    base = (settings.litellm_api_base or "").strip().rstrip("/")
    if not base:
        raise RuntimeError(
            "Set LITELLM_API_BASE or LITELLM_PROXY_BASE or LITELLM_URL to your LiteLLM proxy "
            "OpenAI-compatible base URL (e.g. http://127.0.0.1:4000/v1)."
        )
    if "/v1" not in base:
        logger.warning(
            "[LiteLLM] base_url %r does not contain /v1; OpenAI-compatible clients expect "
            "e.g. http://127.0.0.1:4000/v1",
            base,
        )
    model_name = (settings.chat_model or "").strip()
    if not model_name:
        raise RuntimeError(
            "Set CHAT_MODEL in the environment to a model id your LiteLLM proxy serves (see GET /v1/models)."
        )
    timeout = _request_timeout()

    api_key = settings.litellm_key
    assert api_key is not None
    env_openai = (os.getenv("OPENAI_API_KEY") or "").strip()
    if env_openai:
        logger.warning(
            "[LiteLLM] OPENAI_API_KEY is set (suffix …%s). ChatOpenAI uses LITELLM_KEY; "
            "unset OPENAI_API_KEY if LiteLLM reports a different key than you expect.",
            env_openai[-4:] if len(env_openai) >= 4 else env_openai,
        )

    logger.info(
        "[LiteLLM] ChatOpenAI model=%s base_url=%s api_key_suffix=…%s",
        model_name,
        base,
        api_key[-4:] if len(api_key) >= 4 else api_key,
    )

    # No custom httpx: some LangChain builds reject ``http_async_client`` and 500 every request.
    common = dict(
        base_url=base,
        api_key=api_key,
        model=model_name,
        temperature=_temperature(),
    )
    try:
        return ChatOpenAI(**common, timeout=timeout)
    except TypeError:
        return ChatOpenAI(**common, request_timeout=timeout)
