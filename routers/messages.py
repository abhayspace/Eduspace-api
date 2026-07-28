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
    "id,school_id,sender_id,sender_name,sender_role,recipient_id,group_id,"
    "text,media_url,media_type,media_name,hidden_for,created_at"
)

CHAT_PEER_ROLES = (
    # School Management (SCH/ADM school_admin) is not a chat profile — cannot be messaged.
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


def _is_school_portal_account(role: Optional[str], user_code: Optional[str] = None) -> bool:
    """Institutional School Management login — not a person others can message."""
    code = (user_code or "").strip().upper()
    if role == "school_admin" and (code.startswith("SCH") or code.startswith("ADM")):
        return True
    if role in {"school_admin", "office_staff"}:
        return True
    return False


async def _school_portal_user_ids(school_id: str) -> List[str]:
    """All School Management account IDs for a school (SCH + legacy ADM/office_staff)."""
    client = get_client()
    res = (
        await client.table("users")
        .select("id,role,user_code")
        .eq("school_id", school_id)
        .in_("role", ["school_admin", "office_staff"])
        .execute()
    )
    ids: List[str] = []
    for row in res.data or []:
        if _is_school_portal_account(row.get("role"), row.get("user_code")):
            ids.append(row["id"])
    return ids


async def _message_actor_ids(user: dict) -> List[str]:
    """IDs that share this user's message inbox (portal accounts are unified)."""
    if _is_school_portal_account(user.get("role"), user.get("user_code")):
        ids = await _school_portal_user_ids(user["school_id"])
        return ids or [user["id"]]
    return [user["id"]]


async def _canonical_message_sender(user: dict) -> dict:
    """School Management sends as SCH so both devices share one identity."""
    if not _is_school_portal_account(user.get("role"), user.get("user_code")):
        return user
    code = (user.get("user_code") or "").strip().upper()
    if code.startswith("SCH"):
        return user
    client = get_client()
    res = (
        await client.table("users")
        .select("id,email,full_name,role,school_id,user_code,is_active")
        .eq("school_id", user["school_id"])
        .eq("role", "school_admin")
        .like("user_code", "SCH%")
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else user


async def _canonical_school_portal_user(school_id: str) -> Optional[dict]:
    """Prefer the SCH School Management account for a school."""
    client = get_client()
    sch = (
        await client.table("users")
        .select("id,full_name,role,user_code,is_active")
        .eq("school_id", school_id)
        .eq("role", "school_admin")
        .like("user_code", "SCH%")
        .eq("is_active", True)
        .limit(1)
        .execute()
    )
    if sch.data:
        return sch.data[0]
    portal_ids = await _school_portal_user_ids(school_id)
    if not portal_ids:
        return None
    res = (
        await client.table("users")
        .select("id,full_name,role,user_code,is_active")
        .eq("id", portal_ids[0])
        .limit(1)
        .execute()
    )
    return res.data[0] if res.data else None


async def _dm_peer_id_set(school_id: str, peer_user_id: str) -> Set[str]:
    """Expand School Management peers to all portal account ids."""
    client = get_client()
    res = (
        await client.table("users")
        .select("id,role,user_code")
        .eq("school_id", school_id)
        .eq("id", peer_user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return {peer_user_id}
    peer = res.data[0]
    if _is_school_portal_account(peer.get("role"), peer.get("user_code")):
        portal_ids = await _school_portal_user_ids(school_id)
        # Always keep the requested id — legacy ADM/office_staff may sit outside SCH rows.
        return set(portal_ids or []) | {peer_user_id}
    return {peer_user_id}


async def _expanded_dm_peer_ids(school_id: str, requested_peer_id: str, canonical_peer_id: str) -> Set[str]:
    """Union portal expansions for both the opened peer id and the canonical SCH id."""
    ids = await _dm_peer_id_set(school_id, requested_peer_id)
    ids |= await _dm_peer_id_set(school_id, canonical_peer_id)
    ids.add(requested_peer_id)
    ids.add(canonical_peer_id)
    return ids


async def _normalize_dm_peer_id(school_id: str, peer_user_id: str) -> str:
    """Collapse any School Management account id to the canonical SCH id."""
    client = get_client()
    res = (
        await client.table("users")
        .select("id,role,user_code")
        .eq("school_id", school_id)
        .eq("id", peer_user_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        return peer_user_id
    peer = res.data[0]
    if not _is_school_portal_account(peer.get("role"), peer.get("user_code")):
        return peer_user_id
    canonical = await _canonical_school_portal_user(school_id)
    return canonical["id"] if canonical else peer_user_id


def _is_hidden_for_any(row: dict, user_ids: List[str]) -> bool:
    hidden_raw = row.get("hidden_for") or []
    if isinstance(hidden_raw, str):
        hidden = {hidden_raw}
    else:
        hidden = {str(item) for item in list(hidden_raw)}
    return any(str(uid) in hidden for uid in user_ids)


def _visible_rows_for(rows: List[dict], user_ids: List[str]) -> List[dict]:
    return [row for row in rows if not _is_hidden_for_any(row, user_ids)]


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
    hidden_raw = row.get("hidden_for") or []
    if isinstance(hidden_raw, str):
        hidden = {hidden_raw}
    else:
        hidden = {str(item) for item in list(hidden_raw)}
    return str(user_id) in hidden


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


def _is_group_peer(peer_id: Optional[str]) -> bool:
    return bool(peer_id and str(peer_id).startswith("group:"))


def _parse_auto_group(group_id: str) -> Optional[tuple[str, str]]:
    if not group_id.startswith("group:auto:"):
        return None
    rest = group_id[len("group:auto:") :]
    idx = rest.find(":")
    if idx <= 0:
        return None
    class_id = rest[:idx].strip()
    section_id = rest[idx + 1 :].strip()
    if not class_id or not section_id:
        return None
    return class_id, section_id


def _teacher_teaches_section(
    assignments: List[str],
    *,
    class_name: str,
    section_name: str,
    is_class_teacher: bool,
    ct_class: str,
    ct_section: str,
    class_id: str,
    section_id: str,
    ct_class_id: Optional[str],
    ct_section_id: Optional[str],
) -> bool:
    class_key = class_name.strip().lower()
    section_key = section_name.strip().lower()
    for entry in assignments or []:
        value = (entry or "").strip()
        if not value:
            continue
        sep = " - "
        cut = value.rfind(sep)
        entry_class = value[:cut].strip().lower() if cut > 0 else value.lower()
        entry_section = value[cut + len(sep) :].strip().lower() if cut > 0 else ""
        if entry_class != class_key:
            continue
        if entry_section in {"", "all sections"} or entry_section == section_key:
            return True
    if is_class_teacher:
        if ct_class_id and ct_section_id and ct_class_id == class_id and ct_section_id == section_id:
            return True
        if ct_class.strip().lower() == class_key and ct_section.strip().lower() == section_key:
            return True
    return False


async def _assert_group_access(school_id: str, group_id: str, user: dict) -> None:
    """Verify the user may read/write this group thread."""
    role = user.get("role") or ""
    if role in {"school_admin", "principal", "vice_principal", "super_admin", "office_staff"}:
        return

    parsed = _parse_auto_group(group_id)
    if not parsed:
        if group_id.startswith("group:"):
            return
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")

    class_id, section_id = parsed
    client = get_client()

    class_res = (
        await client.table("classes")
        .select("id,name")
        .eq("school_id", school_id)
        .eq("id", class_id)
        .limit(1)
        .execute()
    )
    section_res = (
        await client.table("sections")
        .select("id,name,class_id")
        .eq("school_id", school_id)
        .eq("id", section_id)
        .limit(1)
        .execute()
    )
    if not class_res.data or not section_res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Class group not found")
    class_name = class_res.data[0].get("name") or ""
    section_name = section_res.data[0].get("name") or ""

    if role == "teacher":
        teacher = (
            await client.table("teachers")
            .select(
                "classes_teaching,is_class_teacher,class_teacher_class_id,class_teacher_section_id"
            )
            .eq("school_id", school_id)
            .eq("user_id", user["id"])
            .limit(1)
            .execute()
        )
        if not teacher.data:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this group")
        profile = teacher.data[0]
        ct_class = ""
        ct_section = ""
        if _teacher_teaches_section(
            profile.get("classes_teaching") or [],
            class_name=class_name,
            section_name=section_name,
            is_class_teacher=bool(profile.get("is_class_teacher")),
            ct_class=ct_class,
            ct_section=ct_section,
            class_id=class_id,
            section_id=section_id,
            ct_class_id=profile.get("class_teacher_class_id"),
            ct_section_id=profile.get("class_teacher_section_id"),
        ):
            return
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this group")

    if role == "student":
        student = (
            await client.table("students")
            .select("id")
            .eq("school_id", school_id)
            .eq("user_id", user["id"])
            .eq("class_id", class_id)
            .eq("section_id", section_id)
            .limit(1)
            .execute()
        )
        if student.data:
            return
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this group")

    raise HTTPException(status.HTTP_403_FORBIDDEN, "Not a member of this group")


async def _group_member_user_ids(school_id: str, group_id: str) -> List[str]:
    """Best-effort member ids for notifications (auto class groups only)."""
    parsed = _parse_auto_group(group_id)
    if not parsed:
        return []
    class_id, section_id = parsed
    client = get_client()
    students = (
        await client.table("students")
        .select("user_id")
        .eq("school_id", school_id)
        .eq("class_id", class_id)
        .eq("section_id", section_id)
        .execute()
    )
    ids = [row["user_id"] for row in (students.data or []) if row.get("user_id")]

    class_res = (
        await client.table("classes")
        .select("name")
        .eq("school_id", school_id)
        .eq("id", class_id)
        .limit(1)
        .execute()
    )
    section_res = (
        await client.table("sections")
        .select("name")
        .eq("school_id", school_id)
        .eq("id", section_id)
        .limit(1)
        .execute()
    )
    class_name = (class_res.data or [{}])[0].get("name") or ""
    section_name = (section_res.data or [{}])[0].get("name") or ""

    teachers = (
        await client.table("teachers")
        .select(
            "user_id,classes_teaching,is_class_teacher,class_teacher_class_id,class_teacher_section_id"
        )
        .eq("school_id", school_id)
        .execute()
    )
    for profile in teachers.data or []:
        if _teacher_teaches_section(
            profile.get("classes_teaching") or [],
            class_name=class_name,
            section_name=section_name,
            is_class_teacher=bool(profile.get("is_class_teacher")),
            ct_class="",
            ct_section="",
            class_id=class_id,
            section_id=section_id,
            ct_class_id=profile.get("class_teacher_class_id"),
            ct_section_id=profile.get("class_teacher_section_id"),
        ):
            uid = profile.get("user_id")
            if uid:
                ids.append(uid)
    return list(dict.fromkeys(ids))


def _split_recipient(recipient_id: Optional[str]) -> tuple[Optional[str], Optional[str]]:
    """Return (dm_recipient_id, group_id)."""
    if isinstance(recipient_id, (list, tuple)):
        recipient_id = recipient_id[0] if recipient_id else None
    if not recipient_id:
        return None, None
    value = str(recipient_id).strip()
    if not value:
        return None, None
    if _is_group_peer(value):
        return None, value
    return value, None


async def _persist_message(
    school_id: str,
    sender_id: str,
    sender_name: str,
    sender_role: str,
    text: str,
    recipient_id: Optional[str] = None,
    group_id: Optional[str] = None,
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
    if group_id:
        row["group_id"] = group_id
    inserted = await client.table("messages").insert(row).execute()
    if not inserted.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to send message")
    return ChatMessage(**inserted.data[0])


async def _assert_peer(school_id: str, peer_user_id: str, user: dict) -> dict:
    """Validate a DM recipient (teacher, staff, or School Management)."""
    self_ids = set(await _message_actor_ids(user))
    if peer_user_id in self_ids:
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
    role = peer.get("role") or ""
    # Teachers/staff may message School Management (routed to canonical SCH).
    if _is_school_portal_account(role, peer.get("user_code")):
        canonical = await _canonical_school_portal_user(school_id)
        if not canonical:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "School Management not found")
        if canonical["id"] in self_ids:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot message yourself")
        return canonical
    if role not in CHAT_PEER_ROLES:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot message this person")
    return peer


async def _assert_existing_dm_peer(school_id: str, peer_user_id: str, user: dict) -> dict:
    """Allow managing an existing DM with any same-school person (incl. School Management)."""
    self_ids = set(await _message_actor_ids(user))
    if peer_user_id in self_ids:
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
    if _is_school_portal_account(peer.get("role"), peer.get("user_code")):
        canonical = await _canonical_school_portal_user(school_id)
        if canonical and canonical["id"] in self_ids:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot message yourself")
        return canonical or peer
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
    me_ids = set(await _message_actor_ids(user))
    peers = [
        row
        for row in (res.data or [])
        if row["id"] not in me_ids and not _is_school_portal_account(row.get("role"), row.get("user_code"))
    ]

    out = [
        ChatPeerOut(
            user_id=row["id"],
            full_name=row.get("full_name") or "User",
            role=row.get("role") or "",
            user_code=row.get("user_code") or "",
        )
        for row in peers
    ]

    # Teachers/staff can start (or reopen) a chat with School Management.
    if not _is_school_portal_account(user.get("role"), user.get("user_code")):
        canonical = await _canonical_school_portal_user(user["school_id"])
        if canonical and canonical["id"] not in me_ids:
            out.insert(
                0,
                ChatPeerOut(
                    user_id=canonical["id"],
                    full_name="School Management",
                    role=canonical.get("role") or "school_admin",
                    user_code=canonical.get("user_code") or "",
                ),
            )
    return out


@router.get("/messages/threads", response_model=List[ChatThreadOut])
async def list_chat_threads(user: dict = Depends(current_user)) -> List[ChatThreadOut]:
    client = get_client()
    me = user["id"]
    me_ids = await _message_actor_ids(user)
    me_id_set = set(me_ids)
    school_id = user["school_id"]
    await purge_expired_messages(school_id)
    cutoff = retention_cutoff_iso()

    sent = (
        await client.table("messages")
        .select(_COLUMNS)
        .eq("school_id", school_id)
        .in_("sender_id", me_ids)
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
        .in_("recipient_id", me_ids)
        .gte("created_at", cutoff)
        .order("created_at", desc=True)
        .limit(500)
        .execute()
    )

    portal_ids = set(await _school_portal_user_ids(school_id))
    canonical_portal = await _canonical_school_portal_user(school_id)
    canonical_portal_id = canonical_portal["id"] if canonical_portal else None

    peer_ids: Set[str] = set()
    latest: Dict[str, dict] = {}

    for row in _visible_rows_for(list(sent.data or []) + list(received.data or []), me_ids):
        sender = row.get("sender_id")
        recipient = row.get("recipient_id")
        if sender in me_id_set:
            peer_id = recipient
        else:
            peer_id = sender
        if not peer_id or peer_id in me_id_set:
            continue
        # Collapse SCH/ADM portal accounts into one School Management thread.
        if peer_id in portal_ids and canonical_portal_id:
            peer_id = canonical_portal_id
        peer_ids.add(peer_id)
        existing = latest.get(peer_id)
        created = row.get("created_at") or ""
        if not existing or created > (existing.get("created_at") or ""):
            latest[peer_id] = row

    if not peer_ids:
        peer_map = {}
    else:
        peers_res = (
            await client.table("users")
            .select("id,full_name,role,user_code")
            .in_("id", list(peer_ids))
            .execute()
        )
        peer_map = {row["id"]: row for row in (peers_res.data or [])}

    # Inbound message counts per peer (messages sent to School Management / me).
    inbound_counts: Dict[str, int] = {}
    for row in _visible_rows_for(list(received.data or []), me_ids):
        sender = row.get("sender_id")
        if not sender or sender in me_id_set:
            continue
        peer_id = sender
        if peer_id in portal_ids and canonical_portal_id:
            peer_id = canonical_portal_id
        inbound_counts[peer_id] = inbound_counts.get(peer_id, 0) + 1

    threads: List[ChatThreadOut] = []
    for peer_id, row in latest.items():
        peer = peer_map.get(peer_id, {})
        created_raw = row.get("created_at")
        if isinstance(created_raw, datetime):
            created_at = created_raw
        else:
            created_at = datetime.fromisoformat(str(created_raw).replace("Z", "+00:00"))
        peer_name = peer.get("full_name") or (
            row.get("sender_name") if row.get("sender_id") not in me_id_set else "Chat"
        )
        peer_role = peer.get("role") or (
            row.get("sender_role") if row.get("sender_id") not in me_id_set else ""
        )
        peer_user_code = peer.get("user_code") or ""
        if peer_id == canonical_portal_id or (
            peer_id in portal_ids and _is_school_portal_account(peer_role, peer_user_code)
        ):
            peer_name = "School Management"
            peer_role = peer_role or "school_admin"
        threads.append(
            ChatThreadOut(
                peer_id=peer_id,
                peer_name=peer_name,
                peer_role=peer_role,
                peer_user_code=peer_user_code,
                last_message=_preview_text(row.get("text") or "", row.get("media_type")),
                last_message_at=created_at,
                last_sender_id=row.get("sender_id") or "",
                unread_count=inbound_counts.get(peer_id, 0),
            )
        )

    # Class / manual group threads — bump to top on latest group message.
    # School Management / admin dashboards should not see class (auto) groups.
    hide_class_auto_groups = (user.get("role") or "") in {
        "school_admin",
        "office_staff",
        "principal",
        "vice_principal",
        "super_admin",
    } or _is_school_portal_account(user.get("role"), user.get("user_code"))
    group_res = (
        await client.table("messages")
        .select(_COLUMNS)
        .eq("school_id", school_id)
        .not_.is_("group_id", "null")
        .gte("created_at", cutoff)
        .order("created_at", desc=True)
        .limit(500)
        .execute()
    )
    group_latest: Dict[str, dict] = {}
    group_inbound: Dict[str, int] = {}
    access_cache: Dict[str, bool] = {}
    for row in _visible_rows_for(list(group_res.data or []), me_ids):
        group_id = row.get("group_id")
        if not group_id:
            continue
        if hide_class_auto_groups and str(group_id).startswith("group:auto:"):
            continue
        if group_id not in access_cache:
            try:
                await _assert_group_access(school_id, group_id, user)
                access_cache[group_id] = True
            except HTTPException:
                access_cache[group_id] = False
        if not access_cache[group_id]:
            continue
        existing = group_latest.get(group_id)
        created = row.get("created_at") or ""
        if not existing or created > (existing.get("created_at") or ""):
            group_latest[group_id] = row
        sender = row.get("sender_id")
        if sender and sender not in me_id_set:
            group_inbound[group_id] = group_inbound.get(group_id, 0) + 1

    for group_id, row in group_latest.items():
        created_raw = row.get("created_at")
        if isinstance(created_raw, datetime):
            created_at = created_raw
        else:
            created_at = datetime.fromisoformat(str(created_raw).replace("Z", "+00:00"))
        peer_name = await _group_thread_name(school_id, group_id)
        threads.append(
            ChatThreadOut(
                peer_id=group_id,
                peer_name=peer_name,
                peer_role="group",
                peer_user_code="",
                last_message=_preview_text(row.get("text") or "", row.get("media_type")),
                last_message_at=created_at,
                last_sender_id=row.get("sender_id") or "",
                unread_count=group_inbound.get(group_id, 0),
            )
        )

    threads.sort(key=lambda item: item.last_message_at, reverse=True)
    return threads


async def _group_thread_name(school_id: str, group_id: str) -> str:
    parsed = _parse_auto_group(group_id)
    if not parsed:
        return "Group"
    class_id, section_id = parsed
    client = get_client()
    class_res = (
        await client.table("classes")
        .select("name")
        .eq("school_id", school_id)
        .eq("id", class_id)
        .limit(1)
        .execute()
    )
    section_res = (
        await client.table("sections")
        .select("name")
        .eq("school_id", school_id)
        .eq("id", section_id)
        .limit(1)
        .execute()
    )
    class_name = ((class_res.data or [{}])[0].get("name") or "Class").strip()
    section_name = ((section_res.data or [{}])[0].get("name") or "").strip()
    return f"{class_name} - {section_name}" if section_name else class_name


@router.get("/messages", response_model=List[ChatMessage])
async def list_messages(
    peer_id: Optional[str] = Query(default=None),
    user: dict = Depends(current_user),
) -> List[ChatMessage]:
    client = get_client()
    school_id = user["school_id"]
    me = user["id"]
    me_ids = await _message_actor_ids(user)
    await purge_expired_messages(school_id)
    cutoff = retention_cutoff_iso()

    if peer_id:
        if _is_group_peer(peer_id):
            await _assert_group_access(school_id, peer_id, user)
            group_res = (
                await client.table("messages")
                .select(_COLUMNS)
                .eq("school_id", school_id)
                .eq("group_id", peer_id)
                .gte("created_at", cutoff)
                .order("created_at", desc=True)
                .limit(1000)
                .execute()
            )
            rows = _visible_rows_for(list(group_res.data or []), me_ids)
            rows.sort(key=lambda item: item.get("created_at") or "")
            return [_to_chat_message(row) for row in rows]

        peer = await _assert_existing_dm_peer(school_id, peer_id, user)
        peer_ids = await _expanded_dm_peer_ids(school_id, peer_id, peer["id"])
        # Direct thread with a person or unified School Management inbox.
        outbound = (
            await client.table("messages")
            .select(_COLUMNS)
            .eq("school_id", school_id)
            .in_("sender_id", me_ids)
            .in_("recipient_id", list(peer_ids))
            .gte("created_at", cutoff)
            .order("created_at", desc=True)
            .limit(1000)
            .execute()
        )
        inbound = (
            await client.table("messages")
            .select(_COLUMNS)
            .eq("school_id", school_id)
            .in_("sender_id", list(peer_ids))
            .in_("recipient_id", me_ids)
            .gte("created_at", cutoff)
            .order("created_at", desc=True)
            .limit(1000)
            .execute()
        )
        rows = list(outbound.data or []) + list(inbound.data or [])
        rows = _visible_rows_for(rows, me_ids)
        # Rewrite portal aliases to the peerId the client opened (inbox uses canonical SCH).
        display_peer_id = peer_id if peer_id in peer_ids else peer["id"]
        if any(pid != display_peer_id for pid in peer_ids):
            normalized = []
            for row in rows:
                item = dict(row)
                if item.get("sender_id") in peer_ids:
                    item["sender_id"] = display_peer_id
                if item.get("recipient_id") in peer_ids:
                    item["recipient_id"] = display_peer_id
                normalized.append(item)
            rows = normalized
        rows.sort(key=lambda item: item.get("created_at") or "")
        return [_to_chat_message(row) for row in rows]

    # Legacy school broadcast feed (no recipient / no group)
    res = (
        await client.table("messages")
        .select(_COLUMNS)
        .eq("school_id", school_id)
        .is_("recipient_id", "null")
        .is_("group_id", "null")
        .gte("created_at", cutoff)
        .order("created_at", desc=True)
        .limit(200)
        .execute()
    )
    rows = _visible_rows_for(list(reversed(res.data or [])), me_ids)
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
    dm_recipient_id, group_id = _split_recipient(body.recipient_id)
    if group_id:
        await _assert_group_access(user["school_id"], group_id, user)
    elif dm_recipient_id:
        peer = await _assert_peer(user["school_id"], dm_recipient_id, user)
        dm_recipient_id = peer["id"]

    sender = await _canonical_message_sender(user)
    if dm_recipient_id and sender["id"] == dm_recipient_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cannot message yourself")
    msg = await _persist_message(
        user["school_id"],
        sender["id"],
        sender.get("full_name") or user["full_name"],
        sender.get("role") or user["role"],
        body.text,
        recipient_id=dm_recipient_id,
        group_id=group_id,
        media_url=body.media_url,
        media_type=body.media_type,
        media_name=body.media_name,
    )
    payload = _message_payload(msg)
    try:
        await manager.broadcast(user["school_id"], payload)
    except Exception as exc:  # noqa: BLE001
        logger.warning("message broadcast failed: %s", exc)

    preview = _preview_text(body.text, body.media_type)
    try:
        if group_id:
            member_ids = await _group_member_user_ids(user["school_id"], group_id)
            for member_id in member_ids:
                if member_id == sender["id"]:
                    continue
                await notify_user(
                    user["school_id"],
                    member_id,
                    sender.get("full_name") or user["full_name"],
                    preview,
                )
        elif dm_recipient_id:
            notify_ids = await _dm_peer_id_set(user["school_id"], dm_recipient_id)
            for notify_id in notify_ids:
                if notify_id == sender["id"]:
                    continue
                await notify_user(
                    user["school_id"],
                    notify_id,
                    sender.get("full_name") or user["full_name"],
                    preview,
                )
        else:
            await notify_school(
                user["school_id"],
                sender.get("full_name") or user["full_name"],
                preview,
                exclude_user_id=sender["id"],
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("message notify failed: %s", exc)
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


async def _hide_messages_for_users(school_id: str, rows: List[dict], user_ids: List[str]) -> int:
    client = get_client()
    updated = 0
    for row in rows:
        hidden_raw = row.get("hidden_for") or []
        if isinstance(hidden_raw, str):
            hidden = [hidden_raw]
        else:
            hidden = [str(item) for item in list(hidden_raw)]
        changed = False
        for user_id in user_ids:
            uid = str(user_id)
            if uid not in hidden:
                hidden.append(uid)
                changed = True
        if not changed:
            continue
        await (
            client.table("messages")
            .update({"hidden_for": hidden})
            .eq("school_id", school_id)
            .eq("id", row["id"])
            .execute()
        )
        updated += 1
    return updated


async def _hide_messages_for_user(school_id: str, rows: List[dict], user_id: str) -> int:
    return await _hide_messages_for_users(school_id, rows, [user_id])


@router.post("/messages/delete")
async def delete_messages(body: ChatDeleteIn, user: dict = Depends(current_user)) -> dict:
    """Delete selected messages for me, or for everyone when the sender chooses."""
    client = get_client()
    school_id = user["school_id"]
    me_ids = set(await _message_actor_ids(user))
    ids = [item for item in body.message_ids if item]
    if not ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No messages selected")

    res = (
        await client.table("messages")
        .select("id,sender_id,recipient_id,group_id,media_url,hidden_for")
        .eq("school_id", school_id)
        .in_("id", ids)
        .execute()
    )
    allowed = []
    for row in res.data or []:
        if row.get("sender_id") in me_ids or row.get("recipient_id") in me_ids:
            allowed.append(row)
            continue
        group_id = row.get("group_id")
        if group_id:
            try:
                await _assert_group_access(school_id, group_id, user)
                allowed.append(row)
            except HTTPException:
                continue

    if body.scope == "everyone":
        own_rows = [row for row in allowed if row.get("sender_id") in me_ids]
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

    count = await _hide_messages_for_users(school_id, allowed, list(me_ids))
    return {"deleted": count, "scope": "me"}


@router.delete("/messages/thread/{peer_id}")
async def clear_or_delete_thread(
    peer_id: str,
    leave: bool = Query(False),
    user: dict = Depends(current_user),
) -> dict:
    """Hide all messages in a thread for the current user (delete for me)."""
    school_id = user["school_id"]
    me = user["id"]
    me_ids = await _message_actor_ids(user)
    client = get_client()

    if _is_group_peer(peer_id):
        if leave and peer_id.startswith("group:auto:"):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                "Class groups cannot be deleted",
            )
        await _assert_group_access(school_id, peer_id, user)
        group_res = (
            await client.table("messages")
            .select("id,media_url,hidden_for")
            .eq("school_id", school_id)
            .eq("group_id", peer_id)
            .execute()
        )
        count = await _hide_messages_for_users(school_id, list(group_res.data or []), me_ids)
        return {"deleted": count, "scope": "me"}

    peer = await _assert_existing_dm_peer(school_id, peer_id, user)
    peer_ids = await _expanded_dm_peer_ids(school_id, peer_id, peer["id"])
    outbound = (
        await client.table("messages")
        .select("id,media_url,hidden_for")
        .eq("school_id", school_id)
        .in_("sender_id", me_ids)
        .in_("recipient_id", list(peer_ids))
        .execute()
    )
    inbound = (
        await client.table("messages")
        .select("id,media_url,hidden_for")
        .eq("school_id", school_id)
        .in_("sender_id", list(peer_ids))
        .in_("recipient_id", me_ids)
        .execute()
    )
    rows = list(outbound.data or []) + list(inbound.data or [])
    count = await _hide_messages_for_users(school_id, rows, me_ids)
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
            raw_recipient = (data or {}).get("recipient_id") or None
            dm_recipient_id, group_id = _split_recipient(raw_recipient)
            try:
                if group_id:
                    await _assert_group_access(school_id, group_id, user)
                elif dm_recipient_id:
                    peer = await _assert_peer(school_id, dm_recipient_id, user)
                    dm_recipient_id = peer["id"]
            except HTTPException as exc:
                try:
                    await ws.send_json(
                        {
                            "type": "error",
                            "detail": exc.detail if isinstance(exc.detail, str) else "Cannot send message",
                        }
                    )
                except Exception:  # noqa: BLE001
                    pass
                continue
            sender = await _canonical_message_sender(user)
            if dm_recipient_id and sender["id"] == dm_recipient_id:
                continue
            msg = await _persist_message(
                school_id,
                sender["id"],
                sender.get("full_name") or user["full_name"],
                sender.get("role") or user["role"],
                text,
                recipient_id=dm_recipient_id,
                group_id=group_id,
                media_url=media_url,
                media_type=media_type,
                media_name=media_name,
            )
            payload = _message_payload(msg)
            await manager.broadcast(school_id, payload)
            if group_id:
                member_ids = await _group_member_user_ids(school_id, group_id)
                for member_id in member_ids:
                    if member_id == sender["id"]:
                        continue
                    await notify_user(
                        school_id,
                        member_id,
                        sender.get("full_name") or user["full_name"],
                        _preview_text(text, media_type),
                    )
            elif dm_recipient_id:
                notify_ids = await _dm_peer_id_set(school_id, dm_recipient_id)
                preview = _preview_text(text, media_type)
                for notify_id in notify_ids:
                    await notify_user(
                        school_id,
                        notify_id,
                        sender.get("full_name") or user["full_name"],
                        preview,
                    )
    except WebSocketDisconnect:
        manager.disconnect(school_id, ws)
    except Exception as exc:  # noqa: BLE001
        logger.warning("ws_chat error: %s", exc)
        manager.disconnect(school_id, ws)
