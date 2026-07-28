"""Public support / help requests from sign-in."""
import logging

from fastapi import APIRouter, HTTPException, status

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
