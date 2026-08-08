"""Public endpoint for developer messages from the onboarding page."""
import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from services.email_service import send_email

router = APIRouter(prefix="/dev-message", tags=["dev-message"])
logger = logging.getLogger("eduspace.dev_message")

DEV_EMAIL = "abhaytripathi19oct@gmail.com"


class DevMessageIn(BaseModel):
    message: str


class DevMessageOut(BaseModel):
    sent: bool = True


@router.post("/send", response_model=DevMessageOut)
async def send_dev_message(body: DevMessageIn) -> DevMessageOut:
    msg = (body.message or "").strip()
    if not msg:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Message cannot be empty")
    sent = await send_email(
        DEV_EMAIL,
        "Eduspace — Developer Message from Onboarding",
        msg,
    )
    if not sent:
        logger.warning("Developer message email not sent (RESEND_API_KEY may be missing)")
    return DevMessageOut(sent=sent)
