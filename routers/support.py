"""Public support / help requests from sign-in."""
import logging

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, EmailStr

from database import get_client
from schemas.support import ISSUE_LABELS, SupportRequestIn, SupportRequestOut
from services.email_service import send_support_query_email

router = APIRouter(prefix="/support", tags=["support"])
logger = logging.getLogger("eduspace.support")

SUPPORT_INBOX = "eduspace.in@gmail.com"


@router.post("/request", response_model=SupportRequestOut)
async def submit_support_request(body: SupportRequestIn) -> SupportRequestOut:
    issue_label = ISSUE_LABELS.get(body.issue, body.issue)
    title = (body.title or "").strip()
    sent = await send_support_query_email(
        to_address=SUPPORT_INBOX,
        reply_to=body.email,
        issue_label=issue_label,
        user_email=body.email,
        title=title,
        message=body.message.strip(),
        school_name=(body.school_name or "").strip(),
        institution_code=(body.institution_code or "").strip(),
    )
    if not sent:
        logger.warning("Support email not sent (SMTP may be unconfigured); query logged from %s", body.email)
    return SupportRequestOut()


class JoinRequestIn(BaseModel):
    school_name: str
    email: EmailStr
    contact: str
    address: str = ""


JOIN_INBOX = "abhaytripathi19oct@gmail.com"


@router.post("/join")
async def submit_join_request(body: JoinRequestIn) -> dict:
    """Public 'apply for free trial' request — stored + emailed to the team inbox."""
    school = body.school_name.strip()
    if not school:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "School name is required")
    if not body.contact.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Contact number is required")

    client = get_client()
    await client.table("school_join_requests").insert(
        {
            "school_name": school,
            "email": body.email,
            "contact": body.contact.strip(),
            "address": (body.address or "").strip(),
        }
    ).execute()

    message = (
        f"School name: {school}\n"
        f"Email: {body.email}\n"
        f"Contact number: {body.contact.strip()}\n"
        f"School address: {(body.address or '').strip() or '—'}\n\n"
        "The school asked the team to call them and complete registration."
    )
    sent = await send_support_query_email(
        to_address=JOIN_INBOX,
        reply_to=body.email,
        issue_label="New school join request",
        user_email=body.email,
        title=f"Join request — {school}",
        message=message,
        school_name=school,
        institution_code="",
    )
    if not sent:
        logger.warning("Join request email not sent; request logged for %s", body.email)
    return {"ok": True, "sent": bool(sent)}
