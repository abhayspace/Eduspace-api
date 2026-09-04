"""Eddy AI Buddy — Groq chat completions proxy."""
from __future__ import annotations

import json
import logging
from typing import Any, AsyncIterator, Dict, List

import httpx
from fastapi import HTTPException, status

from config import get_settings
from schemas.eddy import EddyChatIn, EddyChatMessage
from services.eddy_school_data import ADMIN_ROLES, try_admin_agent

logger = logging.getLogger("eduspace.eddy")

GROQ_CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_GROQ_MODEL = "openai/gpt-oss-120b"

STYLE_GUIDE = {
    "professional": "Respond in a clear, professional tone suitable for school staff.",
    "friendly": "Respond in a warm, encouraging, friendly tone like a helpful buddy.",
    "teacher": "Respond like an experienced school teacher: clear explanations, examples, and gentle guidance.",
    "simple": "Use very simple words and short sentences. Explain like teaching a beginner.",
}

LENGTH_GUIDE = {
    "short": "Keep answers concise (a few short paragraphs or bullets).",
    "medium": "Give a balanced answer with enough detail and structure.",
    "detailed": "Provide a thorough, well-structured answer with steps and examples where useful.",
}

LANGUAGE_GUIDE = {
    "english": "Respond in English.",
    "hindi": "Respond in Hindi (Devanagari script).",
    "hinglish": "Respond in natural Hinglish (Hindi + English mix), easy for Indian school users.",
}


def build_system_prompt(body: EddyChatIn, user: dict) -> str:
    name = (user.get("full_name") or "there").split()[0]
    role = user.get("role") or "user"
    return (
        "You are Eddy, the AI Buddy for Eduspace School ERP — a helpful assistant for "
        "teachers, students, parents, and school admins in India.\n"
        f"The user's first name is {name}. Their role is {role}.\n"
        "You can help with homework, notes, lesson plans, question papers, coding, "
        "school ERP workflows, exams, grammar, translation, and general knowledge.\n"
        "Be accurate, safe for school use, and avoid harmful content.\n"
        "Use markdown when helpful (headings, bullets, fenced code blocks).\n"
        f"{STYLE_GUIDE[body.style]}\n"
        f"{LENGTH_GUIDE[body.length]}\n"
        f"{LANGUAGE_GUIDE[body.language]}\n"
    )


def to_groq_messages(body: EddyChatIn, user: dict) -> List[Dict[str, Any]]:
    messages: List[Dict[str, Any]] = [
        {"role": "system", "content": build_system_prompt(body, user)},
    ]
    for item in body.history[-20:]:
        text = item.content.strip()
        if not text:
            continue
        role = "user" if item.role == "user" else "assistant"
        messages.append({"role": role, "content": text})
    messages.append({"role": "user", "content": body.message.strip()})
    return messages


def _require_groq() -> tuple[str, str]:
    settings = get_settings()
    api_key = (settings.groq_api_key or "").strip()
    model = (settings.groq_model or DEFAULT_GROQ_MODEL).strip()
    if not api_key:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Eddy AI is not configured (missing GROQ_API_KEY).",
        )
    return api_key, model


def _raise_for_status(status_code: int, detail: str, model: str = "") -> None:
    logger.warning("Eddy Groq error %s: %s (model=%s)", status_code, detail, model)
    if status_code in (401, 403):
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Eddy AI authentication failed. Check GROQ_API_KEY.",
        )
    if status_code == 429:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Eddy is busy right now (Groq rate limit). Wait a minute and try again.",
        )
    if status_code == 404:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Eddy AI model '{model}' was not found (404). It may be deprecated. Update GROQ_MODEL.",
        )
    raise HTTPException(
        status.HTTP_502_BAD_GATEWAY,
        f"Eddy AI error ({status_code}).",
    )


def _extract_text(payload: dict) -> str:
    choices = payload.get("choices") or []
    if not choices:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Empty response from Eddy AI")
    message = (choices[0] or {}).get("message") or {}
    reply = str(message.get("content") or "").strip()
    if not reply:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Empty response from Eddy AI")
    return reply


async def generate_reply(body: EddyChatIn, user: dict) -> tuple[str, str]:
    # Rule-based admin agent — bypasses LLM entirely
    if user.get("role") in ADMIN_ROLES and user.get("school_id"):
        agent_reply = await try_admin_agent(user["school_id"], body.message, user)
        if agent_reply:
            logger.info("Eddy admin agent answered directly (no LLM)")
            return agent_reply, "admin-agent"

    api_key, model = _require_groq()
    payload = {
        "model": model,
        "messages": to_groq_messages(body, user),
        "temperature": 0.7,
        "max_completion_tokens": 2048 if body.length != "detailed" else 4096,
        "stream": False,
    }

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.post(
                GROQ_CHAT_URL,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {api_key}",
                },
                json=payload,
            )
    except httpx.TimeoutException as exc:
        logger.warning("Eddy Groq timeout: %s", exc)
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, "Eddy timed out. Try again.") from exc
    except httpx.HTTPError as exc:
        logger.exception("Eddy Groq network error")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Could not reach Eddy AI.") from exc

    if res.status_code >= 400:
        _raise_for_status(res.status_code, res.text[:400], model)

    return _extract_text(res.json()), model


async def stream_reply(body: EddyChatIn, user: dict) -> AsyncIterator[str]:
    """Stream plain text chunks from Groq chat completions SSE."""
    # Rule-based admin agent — yield entire reply in one chunk
    if user.get("role") in ADMIN_ROLES and user.get("school_id"):
        agent_reply = await try_admin_agent(user["school_id"], body.message, user)
        if agent_reply:
            logger.info("Eddy admin agent answered directly (stream, no LLM)")
            yield agent_reply
            return

    api_key, model = _require_groq()
    payload = {
        "model": model,
        "messages": to_groq_messages(body, user),
        "temperature": 0.7,
        "max_completion_tokens": 2048 if body.length != "detailed" else 4096,
        "stream": True,
    }

    async with httpx.AsyncClient(timeout=90.0) as client:
        async with client.stream(
            "POST",
            GROQ_CHAT_URL,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
                "Accept": "text/event-stream",
            },
            json=payload,
        ) as res:
            if res.status_code >= 400:
                text = (await res.aread()).decode("utf-8", errors="replace")[:400]
                _raise_for_status(res.status_code, text, model)
            async for line in res.aiter_lines():
                if not line or not line.startswith("data:"):
                    continue
                raw = line[5:].strip()
                if not raw or raw == "[DONE]":
                    continue
                try:
                    chunk = json.loads(raw)
                except Exception:
                    continue
                choices = chunk.get("choices") or []
                if not choices:
                    continue
                delta = (choices[0] or {}).get("delta") or {}
                text = delta.get("content")
                if text:
                    yield text
