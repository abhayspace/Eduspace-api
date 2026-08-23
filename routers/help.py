"""Help chat router — in-app messaging between users and the developer.

Users send messages from the "Need Help?" screen; the developer replies from
the developer help inbox. No email is sent.

Sender label format:
  - School admin / principal / vice-principal:  "School Name (CODE)"
  - Teacher / other staff:                      "Full Name (CODE)"
  - Student:                                    "Full Name - ADM123 (CODE)"
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException, status

from database import get_client
from schemas.help import (
    HelpConversationOut,
    HelpMessageOut,
    HelpReplyIn,
    HelpSendIn,
)
from utils.deps import current_user, require_roles

router = APIRouter(prefix="/help", tags=["help"])

DEVELOPER_ROLE = "developer"

_HELP_COLUMNS = "id,user_id,sender,sender_label,message,created_at"


async def _build_sender_label(user: dict) -> str:
    """Build the display label for the sender based on role and school."""
    role = user.get("role") or ""
    full_name = user.get("full_name") or "User"
    school_id = user.get("school_id")

    # Fetch the institution code (and school name for admins).
    code = ""
    school_name = ""
    if school_id:
        client = get_client()
        sres = (
            await client.table("schools")
            .select("school_name,institution_code")
            .eq("id", school_id)
            .limit(1)
            .execute()
        )
        if sres.data:
            school_name = sres.data[0].get("school_name") or ""
            code = sres.data[0].get("institution_code") or ""

    if role in ("school_admin", "principal", "vice_principal"):
        return f"{school_name or full_name} ({code})" if code else full_name

    if role == "student":
        adm = user.get("admission_no") or ""
        if adm and code:
            return f"{full_name} - {adm} ({code})"
        if code:
            return f"{full_name} ({code})"
        return full_name

    # Teacher / other staff
    if code:
        return f"{full_name} ({code})"
    return full_name


async def _find_developer_user() -> dict | None:
    client = get_client()
    res = (
        await client.table("users")
        .select("id,email,full_name,role")
        .eq("role", DEVELOPER_ROLE)
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


# ── User endpoints ────────────────────────────────────────────────────────────

@router.post("/messages", response_model=HelpMessageOut)
async def send_help_message(
    body: HelpSendIn,
    user: dict = Depends(current_user),
) -> HelpMessageOut:
    """Authenticated user sends a help message to the developer."""
    if user.get("role") == DEVELOPER_ROLE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Developer cannot send help messages.")
    label = await _build_sender_label(user)
    client = get_client()
    res = (
        await client.table("help_messages")
        .insert({
            "user_id": user["id"],
            "sender": "user",
            "sender_label": label,
            "message": body.message.strip(),
        })
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not send message")
    row = res.data[0]
    return HelpMessageOut(
        id=row["id"],
        userId=row["user_id"],
        sender=row["sender"],
        senderLabel=row["sender_label"],
        message=row["message"],
        createdAt=row["created_at"],
    )


@router.get("/messages", response_model=List[HelpMessageOut])
async def list_my_help_messages(
    user: dict = Depends(current_user),
) -> List[HelpMessageOut]:
    """List the current user's help conversation (both directions)."""
    if user.get("role") == DEVELOPER_ROLE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Use the developer inbox endpoint.")
    client = get_client()
    res = (
        await client.table("help_messages")
        .select(_HELP_COLUMNS)
        .eq("user_id", user["id"])
        .order("created_at", desc=False)
        .limit(500)
        .execute()
    )
    return [
        HelpMessageOut(
            id=r["id"],
            userId=r["user_id"],
            sender=r["sender"],
            senderLabel=r["sender_label"],
            message=r["message"],
            createdAt=r["created_at"],
        )
        for r in (res.data or [])
    ]


@router.delete("/messages", status_code=status.HTTP_204_NO_CONTENT)
async def clear_my_help_messages(
    user: dict = Depends(current_user),
) -> None:
    """Clear the current user's help conversation."""
    if user.get("role") == DEVELOPER_ROLE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Developer cannot clear help messages here.")
    client = get_client()
    await (
        client.table("help_messages")
        .delete()
        .eq("user_id", user["id"])
        .execute()
    )


# ── Developer endpoints ───────────────────────────────────────────────────────

@router.get("/conversations", response_model=List[HelpConversationOut])
async def list_help_conversations(
    user: dict = Depends(require_roles(DEVELOPER_ROLE)),
) -> List[HelpConversationOut]:
    """Developer: list all user conversations with their messages."""
    client = get_client()
    # Fetch all messages ordered by time.
    res = (
        await client.table("help_messages")
        .select(_HELP_COLUMNS)
        .order("created_at", desc=False)
        .limit(5000)
        .execute()
    )
    rows = res.data or []
    # Group by user_id, preserving the original sender_label.
    convos: dict[str, dict] = {}
    for r in rows:
        uid = r["user_id"]
        if uid not in convos:
            convos[uid] = {
                "userId": uid,
                "senderLabel": r["sender_label"],
                "lastMessage": r["message"],
                "lastAt": r["created_at"],
                "messages": [],
            }
        convos[uid]["messages"].append(
            HelpMessageOut(
                id=r["id"],
                userId=r["user_id"],
                sender=r["sender"],
                senderLabel=r["sender_label"],
                message=r["message"],
                createdAt=r["created_at"],
            )
        )
        convos[uid]["lastMessage"] = r["message"]
        convos[uid]["lastAt"] = r["created_at"]

    # Sort by most recent activity, newest first.
    sorted_convos = sorted(convos.values(), key=lambda c: c["lastAt"], reverse=True)
    return [HelpConversationOut(**c) for c in sorted_convos]


@router.post("/conversations/{user_id}/reply", response_model=HelpMessageOut)
async def reply_to_conversation(
    user_id: str,
    body: HelpReplyIn,
    user: dict = Depends(require_roles(DEVELOPER_ROLE)),
) -> HelpMessageOut:
    """Developer: reply to a user's help conversation."""
    client = get_client()
    # Look up the existing sender_label for this user.
    existing = (
        await client.table("help_messages")
        .select("sender_label")
        .eq("user_id", user_id)
        .order("created_at", desc=False)
        .limit(1)
        .execute()
    )
    if not existing.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Conversation not found")
    label = existing.data[0]["sender_label"]

    res = (
        await client.table("help_messages")
        .insert({
            "user_id": user_id,
            "sender": "developer",
            "sender_label": label,
            "message": body.message.strip(),
        })
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Could not send reply")
    row = res.data[0]
    return HelpMessageOut(
        id=row["id"],
        userId=row["user_id"],
        sender=row["sender"],
        senderLabel=row["sender_label"],
        message=row["message"],
        createdAt=row["created_at"],
    )
