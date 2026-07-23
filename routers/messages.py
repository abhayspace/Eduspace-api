"""School chat: direct messages between staff, plus legacy school broadcast."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional, Set

from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import FileResponse

from database import get_client
from schemas.content import (
    ChatDeleteIn,
    ChatMediaUploadOut,
    ChatMessage,
    ChatPeerOut,
    ChatSendIn,
    ChatThreadOut,
)
from services.chat_media_service import (
    delete_chat_file,
    filename_from_media_url,
    resolve_chat_file,
    save_chat_media,
)
from services.message_retention import purge_expired_messages, retention_cutoff_iso
from services.notification_service import notify_school, notify_user
from utils.deps import current_user, get_user_by_token

router = APIRouter(tags=["messages"])
logger = logging.getLogger("eduspace.messages")

_COLUMNS = (
    "id,school_id,sender_id,sender_name,sender_role,recipient_id,"
    "text,media_url,media_type,media_name,hidden_for,created_at"
)

CHAT_PEER_ROLES = (
    "school_admin",
    "office_staff",
    "principal",
    "vice_principal",
    "teacher",
    "receptionist",
    "accountant",
    "librarian",
    "hostel_manager",
    "transport_manager",
    "school_doctor",
)


class ConnectionManager:
    def __init__(self) -> None:
        self.rooms: Dict[str, Set[WebSocket]] = {}

    async def connect(self, school_id: str, ws: WebSocket) -> None:
        await ws.accept()
        self.rooms.setdefault(school_id, set()).add(ws)

    def disconnect(self, school_id: str, ws: WebSocket) -> None:
        if school_id in self.rooms:
            self.rooms[school_id].discard(ws)

    async def broadcast(self, school_id: str, payload: dict) -> None:
        dead: List[WebSocket] = []
        for ws in list(self.rooms.get(school_id, set())):
            try:
                await ws.send_json(payload)
            except Exception:  # noqa: BLE001
                dead.append(ws)
        for ws in dead:
            self.disconnect(school_id, ws)


manager = ConnectionManager()


def _message_payload(msg: ChatMessage) -> dict:
    payload = msg.model_dump()
    payload["created_at"] = msg.created_at.isoformat()
    payload.pop("hidden_for", None)
    return payload


def _is_hidden_for(row: dict, user_id: str) -> bool:
    hidden = row.get("hidden_for") or []
    return user_id in hidden


def _visible_rows(rows: List[dict], user_id: str) -> List[dict]:
    return [row for row in rows if not _is_hidden_for(row, user_id)]


def _to_chat_message(row: dict) -> ChatMessage:
    data = dict(row)
    data.pop("hidden_for", None)
    return ChatMessage(**data)


def _preview_text(text: str, media_type: Optional[str] = None) -> str:
    value = (text or "").strip()
    if value:
        return value
    if media_type == "image":
        return "Photo"
    if media_type == "video":
        return "Video"
    if media_type == "file":
        return "File"
    return value


async def _persist_message(
    school_id: str,
    sender_id: str,
    sender_name: str,
    sender_role: str,
    text: str,
    recipient_id: Optional[str] = None,
    media_url: Optional[str] = None,
    media_type: Optional[str] = None,
    media_name: Optional[str] = None,
) -> ChatMessage:
    client = get_client()
    row = {
        "school_id": school_id,
        "sender_id": sender_id,
        "sender_name": sender_name,
        "sender_role": sender_role,
        "text": text or "",
        "recipient_id": recipient_id,
        "media_url": media_url,
        "media_type": media_type,
        "media_name": media_name,
    }
    inserted = await client.table("messages").insert(row).execute()
    if not inserted.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to send message")
    return ChatMessage(**inserted.data[0])


async def _assert_peer(school_id: str, peer_user_id: str, self_id: str) -> dict:
    if peer_user_id == self_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot message yourself")
    client = get_client()
    res = (
        await client.table("users")
        .select("id,full_name,role,user_code,is_active")
        .eq("school_id", school_id)
        .eq("id", peer_user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Person not found")
    peer = res.data[0]
    if not peer.get("is_active", True):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Person is inactive")
    if peer.get("role") not in CHAT_PEER_ROLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot message this person")
    return peer


@router.get("/messages/peers", response_model=List[ChatPeerOut])
async def list_chat_peers(user: dict = Depends(current_user)) -> List[ChatPeerOut]:
    client = get_client()
    res = (
        await client.table("users")
        .select("id,full_name,role,user_code")
        .eq("school_id", user["school_id"])
        .eq("is_active", True)
        .in_("role", list(CHAT_PEER_ROLES))
        .order("full_name")
        .execute()
    )
    return [
        ChatPeerOut(
            user_id=row["id"],
            full_name=row.get("full_name") or "User",
            role=row.get("role") or "",
            user_code=row.get("user_code") or "",
        )
        for row in (res.data or [])
        if row["id"] != user["id"]
    ]


@router.get("/messages/threads", response_model=List[ChatThreadOut])
async def list_chat_threads(user: dict = Depends(current_user)) -> List[ChatThreadOut]:
    client = get_client()
    me = user["id"]
    school_id = user["school_id"]
    await purge_expired_messages(school_id)
    cutoff = retention_cutoff_iso()

    sent = (
        await client.table("messages")
        .select(_COLUMNS)
        .eq("school_id", school_id)
        .eq("sender_id", me)
        .not_.is_("recipient_id", "null")
        .gte("created_at", cutoff)
        .order("created_at", desc=True)
        .limit(500)
        .execute()
    )
    received = (
        await client.table("messages")
        .select(_COLUMNS)
        .eq("school_id", school_id)
        .eq("recipient_id", me)
        .gte("created_at", cutoff)
        .order("created_at", desc=True)
        .limit(500)
        .execute()
    )

    peer_ids: Set[str] = set()
    latest: Dict[str, dict] = {}

    for row in _visible_rows(list(sent.data or []) + list(received.data or []), me):
        if row.get("sender_id") == me:
            peer_id = row.get("recipient_id")
        else:
            peer_id = row.get("sender_id")
        if not peer_id:
            continue
        peer_ids.add(peer_id)
        existing = latest.get(peer_id)
        created = row.get("created_at") or ""
        if not existing or created > (existing.get("created_at") or ""):
            latest[peer_id] = row

    if not peer_ids:
        return []

    peers_res = (
        await client.table("users")
        .select("id,full_name,role,user_code")
        .in_("id", list(peer_ids))
        .execute()
    )
    peer_map = {row["id"]: row for row in (peers_res.data or [])}

    peer_map = {row["id"]: row for row in (peers_res.data or [])}

    # Inbound message counts per peer (messages sent to me).
    inbound_counts: Dict[str, int] = {}
    for row in _visible_rows(list(received.data or []), me):
        sender = row.get("sender_id")
        if not sender:
            continue
        inbound_counts[sender] = inbound_counts.get(sender, 0) + 1

    threads: List[ChatThreadOut] = []
    for peer_id, row in latest.items():
        peer = peer_map.get(peer_id, {})
        created_raw = row.get("created_at")
        if isinstance(created_raw, datetime):
            created_at = created_raw
        else:
            created_at = datetime.fromisoformat(str(created_raw).replace("Z", "+00:00"))
        threads.append(
            ChatThreadOut(
                peer_id=peer_id,
                peer_name=peer.get("full_name")
                or (row.get("sender_name") if row.get("sender_id") != me else "Chat"),
                peer_role=peer.get("role")
                or (row.get("sender_role") if row.get("sender_id") != me else ""),
                peer_user_code=peer.get("user_code") or "",
                last_message=_preview_text(row.get("text") or "", row.get("media_type")),
                last_message_at=created_at,
                last_sender_id=row.get("sender_id") or "",
                unread_count=inbound_counts.get(peer_id, 0),
            )
        )

    threads.sort(key=lambda item: item.last_message_at, reverse=True)
    return threads


@router.get("/messages", response_model=List[ChatMessage])
async def list_messages(
    peer_id: Optional[str] = Query(default=None),
    user: dict = Depends(current_user),
) -> List[ChatMessage]:
    client = get_client()
    school_id = user["school_id"]
    me = user["id"]
    await purge_expired_messages(school_id)
    cutoff = retention_cutoff_iso()

    if peer_id:
        await _assert_peer(school_id, peer_id, me)
        # Direct thread: messages between me and peer in either direction (within 1 year)
        outbound = (
            await client.table("messages")
            .select(_COLUMNS)
            .eq("school_id", school_id)
            .eq("sender_id", me)
            .eq("recipient_id", peer_id)
            .gte("created_at", cutoff)
            .order("created_at", desc=True)
            .limit(1000)
            .execute()
        )
        inbound = (
            await client.table("messages")
            .select(_COLUMNS)
            .eq("school_id", school_id)
            .eq("sender_id", peer_id)
            .eq("recipient_id", me)
            .gte("created_at", cutoff)
            .order("created_at", desc=True)
            .limit(1000)
            .execute()
        )
        rows = list(outbound.data or []) + list(inbound.data or [])
        rows = _visible_rows(rows, me)
        rows.sort(key=lambda item: item.get("created_at") or "")
        return [_to_chat_message(row) for row in rows]

    # Legacy school broadcast feed (no recipient)
    res = (
        await client.table("messages")
        .select(_COLUMNS)
        .eq("school_id", school_id)
        .is_("recipient_id", "null")
        .gte("created_at", cutoff)
        .order("created_at", desc=True)
        .limit(200)
        .execute()
    )
    rows = _visible_rows(list(reversed(res.data or [])), me)
    return [_to_chat_message(row) for row in rows]


@router.post("/messages/upload", response_model=ChatMediaUploadOut)
async def upload_chat_media(
    file: UploadFile = File(...),
    user: dict = Depends(current_user),
) -> ChatMediaUploadOut:
    saved = await save_chat_media(user["school_id"], file)
    return ChatMediaUploadOut(**saved)


@router.get("/messages/files/{filename}")
async def get_chat_file(
    filename: str,
    user: dict = Depends(current_user),
) -> FileResponse:
    path, mime = resolve_chat_file(user["school_id"], filename)
    return FileResponse(path, media_type=mime, filename=filename)


@router.post("/messages", response_model=ChatMessage)
async def post_message(body: ChatSendIn, user: dict = Depends(current_user)) -> ChatMessage:
    recipient_id = body.recipient_id
    if recipient_id:
        await _assert_peer(user["school_id"], recipient_id, user["id"])

    msg = await _persist_message(
        user["school_id"],
        user["id"],
        user["full_name"],
        user["role"],
        body.text,
        recipient_id=recipient_id,
        media_url=body.media_url,
        media_type=body.media_type,
        media_name=body.media_name,
    )
    payload = _message_payload(msg)
    await manager.broadcast(user["school_id"], payload)

    preview = _preview_text(body.text, body.media_type)
    if recipient_id:
        await notify_user(
            user["school_id"],
            recipient_id,
            user["full_name"],
            preview,
        )
    else:
        await notify_school(
            user["school_id"],
            user["full_name"],
            preview,
            exclude_user_id=user["id"],
        )
    return msg


async def _delete_message_rows(school_id: str, rows: List[dict]) -> int:
    client = get_client()
    deleted = 0
    for row in rows:
        media_url = row.get("media_url")
        if media_url:
            delete_chat_file(school_id, filename_from_media_url(media_url))
        await client.table("messages").delete().eq("school_id", school_id).eq("id", row["id"]).execute()
        deleted += 1
    return deleted


async def _hide_messages_for_user(school_id: str, rows: List[dict], user_id: str) -> int:
    client = get_client()
    updated = 0
    for row in rows:
        hidden = list(row.get("hidden_for") or [])
        if user_id in hidden:
            continue
        hidden.append(user_id)
        await (
            client.table("messages")
            .update({"hidden_for": hidden})
            .eq("school_id", school_id)
            .eq("id", row["id"])
            .execute()
        )
        updated += 1
    return updated


@router.post("/messages/delete")
async def delete_messages(body: ChatDeleteIn, user: dict = Depends(current_user)) -> dict:
    """Delete selected messages for me, or for everyone when the sender chooses."""
    client = get_client()
    school_id = user["school_id"]
    me = user["id"]
    ids = [item for item in body.message_ids if item]
    if not ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No messages selected")

    res = (
        await client.table("messages")
        .select("id,sender_id,recipient_id,media_url,hidden_for")
        .eq("school_id", school_id)
        .in_("id", ids)
        .execute()
    )
    allowed = [
        row
        for row in (res.data or [])
        if row.get("sender_id") == me or row.get("recipient_id") == me
    ]

    if body.scope == "everyone":
        own_rows = [row for row in allowed if row.get("sender_id") == me]
        if not own_rows:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Only your own messages can be deleted for everyone",
            )
        count = await _delete_message_rows(school_id, own_rows)
        await manager.broadcast(
            school_id,
            {
                "type": "messages_deleted",
                "scope": "everyone",
                "message_ids": [row["id"] for row in own_rows],
            },
        )
        return {"deleted": count, "scope": "everyone"}

    count = await _hide_messages_for_user(school_id, allowed, me)
    return {"deleted": count, "scope": "me"}


@router.delete("/messages/thread/{peer_id}")
async def clear_or_delete_thread(peer_id: str, user: dict = Depends(current_user)) -> dict:
    """Hide all direct messages between the current user and peer (delete for me)."""
    school_id = user["school_id"]
    me = user["id"]
    await _assert_peer(school_id, peer_id, me)
    client = get_client()

    outbound = (
        await client.table("messages")
        .select("id,media_url,hidden_for")
        .eq("school_id", school_id)
        .eq("sender_id", me)
        .eq("recipient_id", peer_id)
        .execute()
    )
    inbound = (
        await client.table("messages")
        .select("id,media_url,hidden_for")
        .eq("school_id", school_id)
        .eq("sender_id", peer_id)
        .eq("recipient_id", me)
        .execute()
    )
    rows = list(outbound.data or []) + list(inbound.data or [])
    count = await _hide_messages_for_user(school_id, rows, me)
    return {"deleted": count, "scope": "me"}


@router.websocket("/ws/chat")
async def ws_chat(ws: WebSocket, token: str = Query(...)) -> None:
    try:
        user = await get_user_by_token(token)
    except Exception:  # noqa: BLE001
        await ws.close(code=4401)
        return

    school_id = user["school_id"]
    await manager.connect(school_id, ws)
    try:
        while True:
            data = await ws.receive_json()
            text = ((data or {}).get("text") or "").strip()[:1000]
            media_url = ((data or {}).get("media_url") or "").strip() or None
            media_type = (data or {}).get("media_type") or None
            media_name = (data or {}).get("media_name") or None
            if not text and not media_url:
                continue
            if media_url and media_type not in ("image", "video", "file"):
                continue
            recipient_id = (data or {}).get("recipient_id") or None
            if recipient_id:
                try:
                    await _assert_peer(school_id, recipient_id, user["id"])
                except HTTPException:
                    continue
            msg = await _persist_message(
                school_id,
                user["id"],
                user["full_name"],
                user["role"],
                text,
                recipient_id=recipient_id,
                media_url=media_url,
                media_type=media_type,
                media_name=media_name,
            )
            payload = _message_payload(msg)
            await manager.broadcast(school_id, payload)
            if recipient_id:
                await notify_user(
                    school_id,
                    recipient_id,
                    user["full_name"],
                    _preview_text(text, media_type),
                )
    except WebSocketDisconnect:
        manager.disconnect(school_id, ws)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ws_chat error: %s", exc)
        manager.disconnect(school_id, ws)
