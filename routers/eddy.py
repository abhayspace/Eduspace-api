"""Eddy AI Buddy chat endpoints."""
from __future__ import annotations

import json
import logging

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from config import get_settings
from schemas.eddy import EddyChatIn, EddyChatOut
from services.eddy_service import DEFAULT_GROQ_MODEL, generate_reply, stream_reply
from utils.deps import current_user

router = APIRouter(prefix="/eddy", tags=["eddy"])
public_router = APIRouter(prefix="/eddy", tags=["eddy"])
logger = logging.getLogger("eduspace.eddy")


@router.get("/debug")
async def eddy_debug(user: dict = Depends(current_user)) -> dict:
    """Diagnostic: shows which Groq model Eddy will use."""
    settings = get_settings()
    return {
        "configured_model": settings.groq_model,
        "code_default": DEFAULT_GROQ_MODEL,
        "api_key_set": bool((settings.groq_api_key or "").strip()),
    }


@router.post("/chat", response_model=EddyChatOut)
async def eddy_chat(body: EddyChatIn, user: dict = Depends(current_user)) -> EddyChatOut:
    reply, model = await generate_reply(body, user)
    return EddyChatOut(reply=reply, model=model)


@router.post("/chat/stream")
async def eddy_chat_stream(body: EddyChatIn, user: dict = Depends(current_user)):
    async def event_gen():
        try:
            async for chunk in stream_reply(body, user):
                yield f"data: {json.dumps({'text': chunk}, ensure_ascii=False)}\n\n"
            yield "data: {\"done\": true}\n\n"
        except Exception as exc:
            logger.exception("Eddy stream failed")
            message = getattr(exc, "detail", None) or str(exc) or "Eddy stream failed"
            yield f"data: {json.dumps({'error': str(message)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@public_router.post("/public-chat", response_model=EddyChatOut)
async def eddy_public_chat(body: EddyChatIn) -> EddyChatOut:
    guest_user = {"full_name": "Guest", "role": "visitor"}
    reply, model = await generate_reply(body, guest_user)
    return EddyChatOut(reply=reply, model=model)
