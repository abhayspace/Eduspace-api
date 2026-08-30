"""Transport Management — service layer with role-based authorization.

All queries are scoped by school_id. Student/parent users can only see
transport data for their linked student. Transport managers have operational
access; school admins have full CRUD.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import List, Optional

from fastapi import HTTPException, status

from database import get_client
from schemas.transport import (
    MyTransportOut,
    TransportAnalyticsOut,
    TransportAssignmentCreateIn,
    TransportAssignmentOut,
    TransportAssignmentUpdateIn,
    TransportDashboardOut,
    TransportRequestCreateIn,
    TransportRequestDecideIn,
    TransportRequestOut,
    TransportRouteCreateIn,
    TransportRouteOut,
    TransportRouteOccupancyOut,
    TransportRouteUpdateIn,
    TransportStaffCreateIn,
    TransportStaffOut,
    TransportStaffUpdateIn,
    TransportStopOut,
    TransportUpdateCreateIn,
    TransportUpdateOut,
    TransportVehicleCreateIn,
    TransportVehicleOut,
    TransportVehicleUpdateIn,
)

logger = logging.getLogger("eduspace.transport")

_ADMIN_ROLES = {"school_admin", "principal", "vice_principal", "super_admin"}
_MANAGER_ROLES = _ADMIN_ROLES | {"transport_manager"}
_STUDENT_PARENT_ROLES = {"student", "parent"}

_STAFF_COLS = (
    "id,school_id,full_name,role,mobile,email,license_no,license_expiry,"
    "employee_no,status,notes,is_active,created_at,updated_at"
)
_VEHICLE_COLS = (
    "id,school_id,vehicle_number,vehicle_type,capacity,driver_staff_id,"
    "attendant_staff_id,route_id,status,maintenance_status,registration_expiry,"
    "insurance_expiry,notes,is_archived,created_at,updated_at"
)
_ROUTE_COLS = (
    "id,school_id,name,route_code,vehicle_id,driver_staff_id,status,pickup_start,"
    "drop_end,is_active,notes,created_at,updated_at"
)
_STOP_COLS = "id,school_id,route_id,name,stop_order,pickup_time,drop_time,landmark"
_ASSIGN_COLS = (
    "id,school_id,student_id,route_id,vehicle_id,pickup_stop_id,drop_stop_id,"
    "pickup_time,drop_time,status,effective_from,effective_to,notes,created_at,updated_at"
)
_REQUEST_COLS = (
    "id,school_id,student_id,requester_user_id,request_type,reason,preferred_route_id,"
    "preferred_stop_id,effective_date,status,response_note,decided_by_user_id,decided_at,"
    "created_at,updated_at"
)
_UPDATE_COLS = (
    "id,school_id,route_id,vehicle_id,title,body,update_type,created_by_user_id,created_at,updated_at"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _is_admin(user: dict) -> bool:
    return user.get("role") in _ADMIN_ROLES


def _is_manager(user: dict) -> bool:
    return user.get("role") in _MANAGER_ROLES


def _is_student_or_parent(user: dict) -> bool:
    return user.get("role") in _STUDENT_PARENT_ROLES


async def _resolve_student_id(school_id: str, user: dict) -> Optional[str]:
    """Return the student id linked to a student/parent user."""
    role = user.get("role")
    client = get_client()
    if role == "student":
        res = (
            await client.table("students")
            .select("id")
            .eq("school_id", school_id)
            .eq("user_id", user["id"])
            .limit(1)
            .execute()
        )
        return res.data[0]["id"] if res.data else None
    if role == "parent":
        res = (
            await client.table("parents")
            .select("student_id")
            .eq("school_id", school_id)
            .eq("user_id", user["id"])
            .limit(1)
            .execute()
        )
        if res.data and res.data[0].get("student_id"):
            return res.data[0]["student_id"]
    return None


async def _student_name_map(school_id: str, student_ids: List[str]) -> dict:
    if not student_ids:
        return {}
    client = get_client()
    res = (
        await client.table("students")
        .select("id,user_id,class_id,section_id,roll_no")
        .eq("school_id", school_id)
        .in_("id", student_ids)
        .execute()
    )
    rows = res.data or []
    user_ids = [r["user_id"] for r in rows if r.get("user_id")]
    class_ids = list({r["class_id"] for r in rows if r.get("class_id")})
    section_ids = list({r["section_id"] for r in rows if r.get("section_id")})

    users_map: dict = {}
    if user_ids:
        ures = (
            await client.table("users")
            .select("id,full_name,admission_no")
            .in_("id", user_ids)
            .execute()
        )
        users_map = {u["id"]: u for u in (ures.data or [])}
    classes_map: dict = {}
    if class_ids:
        cres = (
            await client.table("classes")
            .select("id,name")
            .in_("id", class_ids)
            .execute()
        )
        classes_map = {c["id"]: c["name"] for c in (cres.data or [])}
    sections_map: dict = {}
    if section_ids:
        sres = (
            await client.table("sections")
            .select("id,name")
            .in_("id", section_ids)
            .execute()
        )
        sections_map = {s["id"]: s["name"] for s in (sres.data or [])}

    out: dict = {}
    for r in rows:
        u = users_map.get(r.get("user_id"), {})
        out[r["id"]] = {
            "student_name": u.get("full_name", ""),
            "admission_no": u.get("admission_no"),
            "class_name": classes_map.get(r.get("class_id"), ""),
            "section_name": sections_map.get(r.get("section_id"), ""),
        }
    return out


async def _staff_name_map(school_id: str, staff_ids: List[str]) -> dict:
    if not staff_ids:
        return {}
    client = get_client()
    res = (
        await client.table("transport_staff")
        .select("id,full_name")
        .eq("school_id", school_id)
        .in_("id", staff_ids)
        .execute()
    )
    return {r["id"]: r["full_name"] for r in (res.data or [])}


async def _user_name_map(user_ids: List[str]) -> dict:
    if not user_ids:
        return {}
    client = get_client()
    res = (
        await client.table("users")
        .select("id,full_name")
        .in_("id", user_ids)
        .execute()
    )
    return {r["id"]: r["full_name"] for r in (res.data or [])}


async def _vehicle_name_map(school_id: str, vehicle_ids: List[str]) -> dict:
    if not vehicle_ids:
        return {}
    client = get_client()
    res = (
        await client.table("transport_vehicles")
        .select("id,vehicle_number,capacity")
        .eq("school_id", school_id)
        .in_("id", vehicle_ids)
        .execute()
    )
    return {r["id"]: r for r in (res.data or [])}


async def _route_name_map(school_id: str, route_ids: List[str]) -> dict:
    if not route_ids:
        return {}
    client = get_client()
    res = (
        await client.table("transport_routes")
        .select("id,name,vehicle_id")
        .eq("school_id", school_id)
        .in_("id", route_ids)
        .execute()
    )
    return {r["id"]: r for r in (res.data or [])}


async def _stop_name_map(school_id: str, stop_ids: List[str]) -> dict:
    if not stop_ids:
        return {}
    client = get_client()
    res = (
        await client.table("transport_route_stops")
        .select("id,name,route_id")
        .eq("school_id", school_id)
        .in_("id", stop_ids)
        .execute()
    )
    return {r["id"]: r for r in (res.data or [])}


async def _count_assignments_for_vehicle(school_id: str, vehicle_id: str) -> int:
    client = get_client()
    res = (
        await client.table("transport_assignments")
        .select("id", count="exact")
        .eq("school_id", school_id)
        .eq("vehicle_id", vehicle_id)
        .eq("status", "active")
        .execute()
    )
    return res.count or 0


async def _count_assignments_for_route(school_id: str, route_id: str) -> int:
    client = get_client()
    res = (
        await client.table("transport_assignments")
        .select("id", count="exact")
        .eq("school_id", school_id)
        .eq("route_id", route_id)
        .eq("status", "active")
        .execute()
    )
    return res.count or 0


async def _load_stops_for_routes(school_id: str, route_ids: List[str]) -> dict:
    if not route_ids:
        return {}
    client = get_client()
    res = (
        await client.table("transport_route_stops")
        .select(_STOP_COLS)
        .eq("school_id", school_id)
        .in_("route_id", route_ids)
        .order("stop_order", desc=False)
        .execute()
    )
    out: dict = {}
    for r in (res.data or []):
        out.setdefault(r["route_id"], []).append(TransportStopOut(**r))
    return out


def _enrich_vehicle(row: dict, driver_map: dict, attendant_map: dict, route_map: dict, assigned: int) -> TransportVehicleOut:
    cap = int(row.get("capacity") or 0)
    return TransportVehicleOut(
        id=row["id"],
        school_id=row["school_id"],
        vehicle_number=row["vehicle_number"],
        vehicle_type=row.get("vehicle_type", "bus"),
        capacity=cap,
        driver_staff_id=row.get("driver_staff_id"),
        driver_name=driver_map.get(row.get("driver_staff_id")),
        attendant_staff_id=row.get("attendant_staff_id"),
        attendant_name=attendant_map.get(row.get("attendant_staff_id")),
        route_id=row.get("route_id"),
        route_name=(route_map.get(row.get("route_id"), {}) or {}).get("name") if row.get("route_id") else None,
        status=row.get("status", "active"),
        maintenance_status=row.get("maintenance_status", "ok"),
        registration_expiry=row.get("registration_expiry"),
        insurance_expiry=row.get("insurance_expiry"),
        notes=row.get("notes"),
        is_archived=bool(row.get("is_archived", False)),
        assigned_students=assigned,
        available_seats=max(0, cap - assigned),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


# ---------------------------------------------------------------------------
# Dashboard / analytics
# ---------------------------------------------------------------------------
async def get_dashboard(school_id: str, user: dict) -> TransportDashboardOut:
    if not _is_manager(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    client = get_client()

    async def _count(table: str, **filters) -> int:
        q = client.table(table).select("id", count="exact").eq("school_id", school_id)
        for k, v in filters.items():
            q = q.eq(k, v)
        res = await q.execute()
        return res.count or 0

    total_vehicles = await _count("transport_vehicles", is_archived=False)
    active_vehicles = await _count("transport_vehicles", is_archived=False, status="active")
    on_route = await _count("transport_vehicles", is_archived=False, status="on_route")
    maintenance = await _count("transport_vehicles", is_archived=False, status="under_maintenance")
    total_routes = await _count("transport_routes", is_active=True)
    active_routes = await _count("transport_routes", is_active=True, status="active")
    total_drivers = await _count("transport_staff", role="driver", is_active=True)
    total_students = await _count("transport_assignments", status="active")
    pending_requests = await _count("transport_requests", status="pending")
    today_scheduled = await _count("transport_routes", is_active=True, status="scheduled")

    return TransportDashboardOut(
        total_vehicles=total_vehicles,
        active_vehicles=active_vehicles,
        on_route_vehicles=on_route,
        under_maintenance_vehicles=maintenance,
        total_routes=total_routes,
        active_routes=active_routes,
        total_drivers=total_drivers,
        total_transport_students=total_students,
        pending_requests=pending_requests,
        today_scheduled_routes=today_scheduled,
    )


async def get_analytics(school_id: str, user: dict) -> TransportAnalyticsOut:
    if not _is_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    client = get_client()

    vehicles_res = (
        await client.table("transport_vehicles")
        .select(_VEHICLE_COLS)
        .eq("school_id", school_id)
        .eq("is_archived", False)
        .execute()
    )
    vehicles = vehicles_res.data or []
    routes_res = (
        await client.table("transport_routes")
        .select(_ROUTE_COLS)
        .eq("school_id", school_id)
        .execute()
    )
    routes = routes_res.data or []

    route_ids = [r["id"] for r in routes]
    vehicle_ids = [v["id"] for v in vehicles]

    # Count active assignments per route and per vehicle
    route_counts: dict = {}
    vehicle_counts: dict = {}
    if route_ids or vehicle_ids:
        assign_res = (
            await client.table("transport_assignments")
            .select("route_id,vehicle_id")
            .eq("school_id", school_id)
            .eq("status", "active")
            .execute()
        )
        for a in assign_res.data or []:
            rid = a.get("route_id")
            vid = a.get("vehicle_id")
            if rid:
                route_counts[rid] = route_counts.get(rid, 0) + 1
            if vid:
                vehicle_counts[vid] = vehicle_counts.get(vid, 0) + 1

    vehicle_map = {v["id"]: v for v in vehicles}
    route_occupancy: List[TransportRouteOccupancyOut] = []
    students_per_route: List[TransportRouteOccupancyOut] = []
    cap_utils: List[float] = []
    for r in routes:
        rid = r["id"]
        vid = r.get("vehicle_id")
        cap = int(vehicle_map.get(vid, {}).get("capacity", 0)) if vid else 0
        assigned = route_counts.get(rid, 0)
        pct = round((assigned / cap) * 100, 1) if cap else 0.0
        vnum = vehicle_map.get(vid, {}).get("vehicle_number") if vid else None
        item = TransportRouteOccupancyOut(
            route_id=rid,
            route_name=r.get("name", ""),
            vehicle_number=vnum,
            capacity=cap,
            assigned_students=assigned,
            occupancy_pct=pct,
        )
        route_occupancy.append(item)
        students_per_route.append(item)
        if cap:
            cap_utils.append(pct)

    total_transport_students = sum(route_counts.values()) or sum(vehicle_counts.values())
    avg_util = round(sum(cap_utils) / len(cap_utils), 1) if cap_utils else 0.0

    return TransportAnalyticsOut(
        total_vehicles=len(vehicles),
        active_vehicles=sum(1 for v in vehicles if v.get("status") == "active"),
        inactive_vehicles=sum(1 for v in vehicles if v.get("status") == "inactive"),
        on_route_vehicles=sum(1 for v in vehicles if v.get("status") == "on_route"),
        under_maintenance_vehicles=sum(1 for v in vehicles if v.get("status") == "under_maintenance"),
        total_routes=len(routes),
        active_routes=sum(1 for r in routes if r.get("status") == "active"),
        total_transport_students=total_transport_students,
        avg_capacity_utilization=avg_util,
        route_occupancy=route_occupancy,
        students_per_route=students_per_route,
    )


# ---------------------------------------------------------------------------
# Staff
# ---------------------------------------------------------------------------
async def list_staff(school_id: str, user: dict, role: Optional[str] = None, status: Optional[str] = None) -> List[TransportStaffOut]:
    if not _is_manager(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    client = get_client()
    q = client.table("transport_staff").select(_STAFF_COLS).eq("school_id", school_id)
    if role:
        q = q.eq("role", role)
    if status:
        q = q.eq("status", status)
    res = await q.order("created_at", desc=True).execute()
    return [TransportStaffOut(**r) for r in (res.data or [])]


async def create_staff(school_id: str, user: dict, body: TransportStaffCreateIn) -> TransportStaffOut:
    if not _is_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    client = get_client()
    row = body.model_dump()
    row["school_id"] = school_id
    res = await client.table("transport_staff").insert(row).execute()
    if not res.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create staff")
    return TransportStaffOut(**res.data[0])


async def update_staff(school_id: str, staff_id: str, user: dict, body: TransportStaffUpdateIn) -> TransportStaffOut:
    if not _is_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    client = get_client()
    payload = {k: v for k, v in body.model_dump().items() if v is not None}
    res = (
        await client.table("transport_staff")
        .update(payload)
        .eq("school_id", school_id)
        .eq("id", staff_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Staff not found")
    return TransportStaffOut(**res.data[0])


async def delete_staff(school_id: str, staff_id: str, user: dict) -> None:
    if not _is_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    client = get_client()
    await client.table("transport_staff").delete().eq("school_id", school_id).eq("id", staff_id).execute()


# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------
async def list_vehicles(
    school_id: str,
    user: dict,
    status: Optional[str] = None,
    maintenance_status: Optional[str] = None,
    route_id: Optional[str] = None,
    include_archived: bool = False,
) -> List[TransportVehicleOut]:
    if not _is_manager(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    client = get_client()
    q = client.table("transport_vehicles").select(_VEHICLE_COLS).eq("school_id", school_id)
    if not include_archived:
        q = q.eq("is_archived", False)
    if status:
        q = q.eq("status", status)
    if maintenance_status:
        q = q.eq("maintenance_status", maintenance_status)
    if route_id:
        q = q.eq("route_id", route_id)
    res = await q.order("created_at", desc=True).execute()
    rows = res.data or []
    staff_ids = list({r["driver_staff_id"] for r in rows if r.get("driver_staff_id")} | {r["attendant_staff_id"] for r in rows if r.get("attendant_staff_id")})
    route_ids = [r["route_id"] for r in rows if r.get("route_id")]
    vehicle_ids = [r["id"] for r in rows]
    driver_map = await _staff_name_map(school_id, list(staff_ids))
    route_map = await _route_name_map(school_id, route_ids)
    # assignment counts per vehicle
    counts: dict = {}
    if vehicle_ids:
        ares = (
            await client.table("transport_assignments")
            .select("vehicle_id")
            .eq("school_id", school_id)
            .eq("status", "active")
            .in_("vehicle_id", vehicle_ids)
            .execute()
        )
        for a in ares.data or []:
            vid = a.get("vehicle_id")
            if vid:
                counts[vid] = counts.get(vid, 0) + 1
    return [_enrich_vehicle(r, driver_map, {}, route_map, counts.get(r["id"], 0)) for r in rows]


async def get_vehicle(school_id: str, vehicle_id: str, user: dict) -> TransportVehicleOut:
    if not _is_manager(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    client = get_client()
    res = (
        await client.table("transport_vehicles")
        .select(_VEHICLE_COLS)
        .eq("school_id", school_id)
        .eq("id", vehicle_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vehicle not found")
    row = res.data[0]
    driver_map = await _staff_name_map(school_id, [row["driver_staff_id"]] if row.get("driver_staff_id") else [])
    route_map = await _route_name_map(school_id, [row["route_id"]] if row.get("route_id") else [])
    assigned = await _count_assignments_for_vehicle(school_id, vehicle_id)
    return _enrich_vehicle(row, driver_map, {}, route_map, assigned)


async def create_vehicle(school_id: str, user: dict, body: TransportVehicleCreateIn) -> TransportVehicleOut:
    if not _is_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    client = get_client()
    row = body.model_dump()
    row["school_id"] = school_id
    try:
        res = await client.table("transport_vehicles").insert(row).execute()
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Could not create vehicle: {exc}")
    if not res.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create vehicle")
    return await get_vehicle(school_id, res.data[0]["id"], user)


async def update_vehicle(school_id: str, vehicle_id: str, user: dict, body: TransportVehicleUpdateIn) -> TransportVehicleOut:
    if not _is_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    client = get_client()
    payload = {k: v for k, v in body.model_dump().items() if v is not None}
    res = (
        await client.table("transport_vehicles")
        .update(payload)
        .eq("school_id", school_id)
        .eq("id", vehicle_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vehicle not found")
    return await get_vehicle(school_id, vehicle_id, user)


async def update_vehicle_status(school_id: str, vehicle_id: str, user: dict, status: str, maintenance_status: Optional[str] = None) -> TransportVehicleOut:
    """Manager-friendly operational status update (no destructive fields)."""
    if not _is_manager(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    client = get_client()
    payload: dict = {"status": status}
    if maintenance_status:
        payload["maintenance_status"] = maintenance_status
    res = (
        await client.table("transport_vehicles")
        .update(payload)
        .eq("school_id", school_id)
        .eq("id", vehicle_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vehicle not found")
    return await get_vehicle(school_id, vehicle_id, user)


async def archive_vehicle(school_id: str, vehicle_id: str, user: dict) -> None:
    if not _is_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    client = get_client()
    await client.table("transport_vehicles").update({"is_archived": True}).eq("school_id", school_id).eq("id", vehicle_id).execute()


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
async def _route_to_out(row: dict, stops: List[TransportStopOut], driver_map: dict, vehicle_map: dict, assigned: int) -> TransportRouteOut:
    vid = row.get("vehicle_id")
    cap = int(vehicle_map.get(vid, {}).get("capacity", 0)) if vid else 0
    return TransportRouteOut(
        id=row["id"],
        school_id=row["school_id"],
        name=row["name"],
        route_code=row.get("route_code"),
        vehicle_id=vid,
        vehicle_number=vehicle_map.get(vid, {}).get("vehicle_number") if vid else None,
        vehicle_capacity=cap,
        driver_staff_id=row.get("driver_staff_id"),
        driver_name=driver_map.get(row.get("driver_staff_id")),
        status=row.get("status", "scheduled"),
        pickup_start=row.get("pickup_start"),
        drop_end=row.get("drop_end"),
        is_active=bool(row.get("is_active", True)),
        notes=row.get("notes"),
        stops=stops,
        assigned_students=assigned,
        available_seats=max(0, cap - assigned),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


async def list_routes(
    school_id: str,
    user: dict,
    status: Optional[str] = None,
    vehicle_id: Optional[str] = None,
    driver_staff_id: Optional[str] = None,
    include_inactive: bool = False,
) -> List[TransportRouteOut]:
    if not _is_manager(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    client = get_client()
    q = client.table("transport_routes").select(_ROUTE_COLS).eq("school_id", school_id)
    if not include_inactive:
        q = q.eq("is_active", True)
    if status:
        q = q.eq("status", status)
    if vehicle_id:
        q = q.eq("vehicle_id", vehicle_id)
    if driver_staff_id:
        q = q.eq("driver_staff_id", driver_staff_id)
    res = await q.order("created_at", desc=True).execute()
    rows = res.data or []
    return await _enrich_routes(school_id, rows)


async def _enrich_routes(school_id: str, rows: list) -> List[TransportRouteOut]:
    if not rows:
        return []
    route_ids = [r["id"] for r in rows]
    vehicle_ids = [r["vehicle_id"] for r in rows if r.get("vehicle_id")]
    staff_ids = [r["driver_staff_id"] for r in rows if r.get("driver_staff_id")]
    stops_map = await _load_stops_for_routes(school_id, route_ids)
    vehicle_map = await _vehicle_name_map(school_id, vehicle_ids)
    driver_map = await _staff_name_map(school_id, staff_ids)
    counts: dict = {}
    if route_ids:
        client = get_client()
        ares = (
            await client.table("transport_assignments")
            .select("route_id")
            .eq("school_id", school_id)
            .eq("status", "active")
            .in_("route_id", route_ids)
            .execute()
        )
        for a in ares.data or []:
            rid = a.get("route_id")
            if rid:
                counts[rid] = counts.get(rid, 0) + 1
    return [
        await _route_to_out(r, stops_map.get(r["id"], []), driver_map, vehicle_map, counts.get(r["id"], 0))
        for r in rows
    ]


async def get_route(school_id: str, route_id: str, user: dict) -> TransportRouteOut:
    # Students/parents may fetch only their assigned route; managers may fetch any.
    client = get_client()
    res = (
        await client.table("transport_routes")
        .select(_ROUTE_COLS)
        .eq("school_id", school_id)
        .eq("id", route_id)
        .limit(1)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Route not found")
    row = res.data[0]
    if _is_student_or_parent(user):
        student_id = await _resolve_student_id(school_id, user)
        if not student_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "No linked student")
        ares = (
            await client.table("transport_assignments")
            .select("id")
            .eq("school_id", school_id)
            .eq("student_id", student_id)
            .eq("route_id", route_id)
            .eq("status", "active")
            .limit(1)
            .execute()
        )
        if not ares.data:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized for this route")
    elif not _is_manager(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    out = (await _enrich_routes(school_id, [row]))
    return out[0]


async def create_route(school_id: str, user: dict, body: TransportRouteCreateIn) -> TransportRouteOut:
    if not _is_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    client = get_client()
    row = body.model_dump(exclude={"stops"})
    row["school_id"] = school_id
    try:
        res = await client.table("transport_routes").insert(row).execute()
    except Exception as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Could not create route: {exc}")
    if not res.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create route")
    route_id = res.data[0]["id"]
    # Insert stops
    for idx, stop in enumerate(body.stops):
        srow = stop.model_dump()
        srow["school_id"] = school_id
        srow["route_id"] = route_id
        if "stop_order" not in srow or srow["stop_order"] is None:
            srow["stop_order"] = idx
        await client.table("transport_route_stops").insert(srow).execute()
    return await get_route(school_id, route_id, user)


async def update_route(school_id: str, route_id: str, user: dict, body: TransportRouteUpdateIn) -> TransportRouteOut:
    if not _is_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    client = get_client()
    payload = {k: v for k, v in body.model_dump(exclude={"stops"}).items() if v is not None}
    res = (
        await client.table("transport_routes")
        .update(payload)
        .eq("school_id", school_id)
        .eq("id", route_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Route not found")
    # Replace stops if provided
    if body.stops is not None:
        await client.table("transport_route_stops").delete().eq("route_id", route_id).execute()
        for idx, stop in enumerate(body.stops):
            srow = stop.model_dump()
            srow["school_id"] = school_id
            srow["route_id"] = route_id
            if "stop_order" not in srow or srow["stop_order"] is None:
                srow["stop_order"] = idx
            await client.table("transport_route_stops").insert(srow).execute()
    return await get_route(school_id, route_id, user)


async def update_route_status(school_id: str, route_id: str, user: dict, route_status: str, notes: Optional[str] = None) -> TransportRouteOut:
    """Manager-friendly operational status update (start/complete/delay/cancel)."""
    if not _is_manager(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    client = get_client()
    payload: dict = {"status": route_status}
    if notes is not None:
        payload["notes"] = notes
    res = (
        await client.table("transport_routes")
        .update(payload)
        .eq("school_id", school_id)
        .eq("id", route_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Route not found")
    return await get_route(school_id, route_id, user)


async def delete_route(school_id: str, route_id: str, user: dict) -> None:
    if not _is_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    client = get_client()
    await client.table("transport_routes").delete().eq("school_id", school_id).eq("id", route_id).execute()


# ---------------------------------------------------------------------------
# Assignments
# ---------------------------------------------------------------------------
async def _enrich_assignment(school_id: str, row: dict, student_map: dict, route_map: dict, vehicle_map: dict, stop_map: dict) -> TransportAssignmentOut:
    s = student_map.get(row["student_id"], {})
    return TransportAssignmentOut(
        id=row["id"],
        school_id=row["school_id"],
        student_id=row["student_id"],
        student_name=s.get("student_name", ""),
        class_name=s.get("class_name", ""),
        section_name=s.get("section_name", ""),
        admission_no=s.get("admission_no"),
        route_id=row.get("route_id"),
        route_name=(route_map.get(row.get("route_id"), {}) or {}).get("name") if row.get("route_id") else None,
        vehicle_id=row.get("vehicle_id"),
        vehicle_number=(vehicle_map.get(row.get("vehicle_id"), {}) or {}).get("vehicle_number") if row.get("vehicle_id") else None,
        pickup_stop_id=row.get("pickup_stop_id"),
        pickup_stop_name=(stop_map.get(row.get("pickup_stop_id"), {}) or {}).get("name") if row.get("pickup_stop_id") else None,
        drop_stop_id=row.get("drop_stop_id"),
        drop_stop_name=(stop_map.get(row.get("drop_stop_id"), {}) or {}).get("name") if row.get("drop_stop_id") else None,
        pickup_time=row.get("pickup_time"),
        drop_time=row.get("drop_time"),
        status=row.get("status", "active"),
        effective_from=row.get("effective_from"),
        effective_to=row.get("effective_to"),
        notes=row.get("notes"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


async def list_assignments(
    school_id: str,
    user: dict,
    class_id: Optional[str] = None,
    section_id: Optional[str] = None,
    route_id: Optional[str] = None,
    status: Optional[str] = None,
    search: Optional[str] = None,
) -> List[TransportAssignmentOut]:
    if not _is_manager(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    client = get_client()
    q = client.table("transport_assignments").select(_ASSIGN_COLS).eq("school_id", school_id)
    if route_id:
        q = q.eq("route_id", route_id)
    if status:
        q = q.eq("status", status)
    res = await q.order("created_at", desc=True).limit(300).execute()
    rows = res.data or []

    # Filter by class/section via students table
    if class_id or section_id or search:
        student_ids = [r["student_id"] for r in rows]
        if not student_ids:
            return []
        sq = client.table("students").select("id,user_id,class_id,section_id").eq("school_id", school_id).in_("id", student_ids)
        if class_id:
            sq = sq.eq("class_id", class_id)
        if section_id:
            sq = sq.eq("section_id", section_id)
        sres = await sq.execute()
        valid_ids = {r["id"] for r in (sres.data or [])}
        rows = [r for r in rows if r["student_id"] in valid_ids]

    return await _enrich_assignments(school_id, rows, search)


async def _enrich_assignments(school_id: str, rows: list, search: Optional[str] = None) -> List[TransportAssignmentOut]:
    if not rows:
        return []
    student_ids = [r["student_id"] for r in rows]
    route_ids = list({r["route_id"] for r in rows if r.get("route_id")})
    vehicle_ids = list({r["vehicle_id"] for r in rows if r.get("vehicle_id")})
    stop_ids = list({r["pickup_stop_id"] for r in rows if r.get("pickup_stop_id")} | {r["drop_stop_id"] for r in rows if r.get("drop_stop_id")})
    student_map = await _student_name_map(school_id, student_ids)
    route_map = await _route_name_map(school_id, route_ids)
    vehicle_map = await _vehicle_name_map(school_id, vehicle_ids)
    stop_map = await _stop_name_map(school_id, stop_ids)
    out = [await _enrich_assignment(school_id, r, student_map, route_map, vehicle_map, stop_map) for r in rows]
    if search:
        s = search.lower()
        out = [a for a in out if s in (a.student_name or "").lower() or s in (a.admission_no or "").lower()]
    return out


async def create_assignment(school_id: str, user: dict, body: TransportAssignmentCreateIn) -> TransportAssignmentOut:
    if not _is_manager(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    client = get_client()
    # Prevent duplicate active assignment
    existing = (
        await client.table("transport_assignments")
        .select("id")
        .eq("school_id", school_id)
        .eq("student_id", body.student_id)
        .eq("status", "active")
        .limit(1)
        .execute()
    )
    if existing.data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Student already has an active transport assignment")
    # Capacity check
    if body.vehicle_id:
        vres = (
            await client.table("transport_vehicles")
            .select("capacity,status,is_archived")
            .eq("school_id", school_id)
            .eq("id", body.vehicle_id)
            .limit(1)
            .execute()
        )
        if not vres.data:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Vehicle not found")
        v = vres.data[0]
        if v.get("is_archived"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Vehicle is archived")
        if v.get("status") in ("under_maintenance", "unavailable"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Vehicle is not available")
        assigned = await _count_assignments_for_vehicle(school_id, body.vehicle_id)
        if assigned + 1 > int(v.get("capacity", 0)):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Vehicle capacity exceeded")
    row = body.model_dump()
    row["school_id"] = school_id
    res = await client.table("transport_assignments").insert(row).execute()
    if not res.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create assignment")
    out = await _enrich_assignments(school_id, [res.data[0]])
    return out[0]


async def update_assignment(school_id: str, assignment_id: str, user: dict, body: TransportAssignmentUpdateIn) -> TransportAssignmentOut:
    if not _is_manager(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    client = get_client()
    payload = {k: v for k, v in body.model_dump().items() if v is not None}
    # Capacity check on vehicle change
    if payload.get("vehicle_id"):
        vres = (
            await client.table("transport_vehicles")
            .select("capacity,status,is_archived")
            .eq("school_id", school_id)
            .eq("id", payload["vehicle_id"])
            .limit(1)
            .execute()
        )
        if not vres.data:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Vehicle not found")
        v = vres.data[0]
        if v.get("is_archived"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Vehicle is archived")
        if v.get("status") in ("under_maintenance", "unavailable"):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Vehicle is not available")
        assigned = await _count_assignments_for_vehicle(school_id, payload["vehicle_id"])
        # Subtract current assignment if it's the same vehicle
        cur = (
            await client.table("transport_assignments")
            .select("vehicle_id")
            .eq("id", assignment_id)
            .limit(1)
            .execute()
        )
        cur_vid = (cur.data or [{}])[0].get("vehicle_id") if cur.data else None
        if cur_vid != payload["vehicle_id"] and assigned + 1 > int(v.get("capacity", 0)):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Vehicle capacity exceeded")
    res = (
        await client.table("transport_assignments")
        .update(payload)
        .eq("school_id", school_id)
        .eq("id", assignment_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    out = await _enrich_assignments(school_id, [res.data[0]])
    return out[0]


async def delete_assignment(school_id: str, assignment_id: str, user: dict) -> None:
    if not _is_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    client = get_client()
    await client.table("transport_assignments").delete().eq("school_id", school_id).eq("id", assignment_id).execute()


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------
async def _enrich_request(school_id: str, row: dict, student_map: dict, route_map: dict, stop_map: dict, user_map: dict) -> TransportRequestOut:
    s = student_map.get(row.get("student_id"), {})
    return TransportRequestOut(
        id=row["id"],
        school_id=row["school_id"],
        student_id=row.get("student_id"),
        student_name=s.get("student_name", ""),
        class_name=s.get("class_name", ""),
        section_name=s.get("section_name", ""),
        requester_user_id=row["requester_user_id"],
        requester_name=user_map.get(row["requester_user_id"], ""),
        request_type=row["request_type"],
        reason=row.get("reason"),
        preferred_route_id=row.get("preferred_route_id"),
        preferred_route_name=(route_map.get(row.get("preferred_route_id"), {}) or {}).get("name") if row.get("preferred_route_id") else None,
        preferred_stop_id=row.get("preferred_stop_id"),
        preferred_stop_name=(stop_map.get(row.get("preferred_stop_id"), {}) or {}).get("name") if row.get("preferred_stop_id") else None,
        effective_date=row.get("effective_date"),
        status=row.get("status", "pending"),
        response_note=row.get("response_note"),
        decided_by_user_id=row.get("decided_by_user_id"),
        decided_by_name=user_map.get(row.get("decided_by_user_id"), "") if row.get("decided_by_user_id") else None,
        decided_at=row.get("decided_at"),
        created_at=row.get("created_at"),
        updated_at=row.get("updated_at"),
    )


async def list_requests(
    school_id: str,
    user: dict,
    request_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
) -> List[TransportRequestOut]:
    client = get_client()
    q = client.table("transport_requests").select(_REQUEST_COLS).eq("school_id", school_id)
    if _is_student_or_parent(user):
        q = q.eq("requester_user_id", user["id"])
    elif not _is_manager(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    if request_type:
        q = q.eq("request_type", request_type)
    if status:
        q = q.eq("status", status)
    res = await q.order("created_at", desc=True).limit(limit).execute()
    rows = res.data or []
    if not rows:
        return []
    student_ids = [r["student_id"] for r in rows if r.get("student_id")]
    route_ids = list({r["preferred_route_id"] for r in rows if r.get("preferred_route_id")})
    stop_ids = list({r["preferred_stop_id"] for r in rows if r.get("preferred_stop_id")})
    user_ids = list({r["requester_user_id"] for r in rows} | {r["decided_by_user_id"] for r in rows if r.get("decided_by_user_id")})
    student_map = await _student_name_map(school_id, student_ids)
    route_map = await _route_name_map(school_id, route_ids)
    stop_map = await _stop_name_map(school_id, stop_ids)
    user_map = await _user_name_map(user_ids)
    return [await _enrich_request(school_id, r, student_map, route_map, stop_map, user_map) for r in rows]


async def create_request(school_id: str, user: dict, body: TransportRequestCreateIn) -> TransportRequestOut:
    client = get_client()
    student_id = body.student_id
    if _is_student_or_parent(user):
        student_id = await _resolve_student_id(school_id, user)
        if not student_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "No linked student found")
    elif not _is_manager(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    if not student_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Student is required")
    row = body.model_dump(exclude={"student_id"})
    row["school_id"] = school_id
    row["student_id"] = student_id
    row["requester_user_id"] = user["id"]
    res = await client.table("transport_requests").insert(row).execute()
    if not res.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create request")
    out = await list_requests(school_id, user, limit=1)
    # The newly created request is the latest for this user; find it.
    for r in out:
        if r.id == res.data[0]["id"]:
            return r
    # Fallback enrichment
    user_map = await _user_name_map([user["id"]])
    student_map = await _student_name_map(school_id, [student_id])
    return await _enrich_request(school_id, res.data[0], student_map, {}, {}, user_map)


async def decide_request(school_id: str, request_id: str, user: dict, body: TransportRequestDecideIn) -> TransportRequestOut:
    if not _is_manager(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    if body.status not in ("approved", "rejected", "completed"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid status")
    client = get_client()
    payload = {
        "status": body.status,
        "response_note": body.response_note,
        "decided_by_user_id": user["id"],
        "decided_at": datetime.now(timezone.utc).isoformat(),
    }
    res = (
        await client.table("transport_requests")
        .update(payload)
        .eq("school_id", school_id)
        .eq("id", request_id)
        .execute()
    )
    if not res.data:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Request not found")
    out = await list_requests(school_id, user, limit=200)
    for r in out:
        if r.id == request_id:
            return r
    user_map = await _user_name_map([user["id"]])
    return await _enrich_request(school_id, res.data[0], {}, {}, {}, user_map)


# ---------------------------------------------------------------------------
# Updates / announcements
# ---------------------------------------------------------------------------
async def list_updates(school_id: str, user: dict, route_id: Optional[str] = None, limit: int = 50) -> List[TransportUpdateOut]:
    client = get_client()
    q = client.table("transport_updates").select(_UPDATE_COLS).eq("school_id", school_id)
    if _is_student_or_parent(user):
        student_id = await _resolve_student_id(school_id, user)
        if not student_id:
            return []
        # Only updates for the student's assigned route(s) + school-wide (route_id is null)
        ares = (
            await client.table("transport_assignments")
            .select("route_id")
            .eq("school_id", school_id)
            .eq("student_id", student_id)
            .eq("status", "active")
            .execute()
        )
        route_ids = [a["route_id"] for a in (ares.data or []) if a.get("route_id")]
        if route_ids:
            q = q.or_(f"route_id.in.({','.join(route_ids)}),route_id.is.null")
        else:
            q = q.is_("route_id", "null")
    elif not _is_manager(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    if route_id:
        q = q.eq("route_id", route_id)
    res = await q.order("created_at", desc=True).limit(limit).execute()
    rows = res.data or []
    if not rows:
        return []
    route_ids = list({r["route_id"] for r in rows if r.get("route_id")})
    vehicle_ids = list({r["vehicle_id"] for r in rows if r.get("vehicle_id")})
    user_ids = [r["created_by_user_id"] for r in rows if r.get("created_by_user_id")]
    route_map = await _route_name_map(school_id, route_ids)
    vehicle_map = await _vehicle_name_map(school_id, vehicle_ids)
    user_map = await _user_name_map(user_ids)
    out: List[TransportUpdateOut] = []
    for r in rows:
        out.append(
            TransportUpdateOut(
                id=r["id"],
                school_id=r["school_id"],
                route_id=r.get("route_id"),
                route_name=(route_map.get(r.get("route_id"), {}) or {}).get("name") if r.get("route_id") else None,
                vehicle_id=r.get("vehicle_id"),
                vehicle_number=(vehicle_map.get(r.get("vehicle_id"), {}) or {}).get("vehicle_number") if r.get("vehicle_id") else None,
                title=r["title"],
                body=r.get("body"),
                update_type=r.get("update_type", "announcement"),
                created_by_user_id=r.get("created_by_user_id"),
                created_by_name=user_map.get(r.get("created_by_user_id"), "") if r.get("created_by_user_id") else None,
                created_at=r.get("created_at"),
            )
        )
    return out


async def create_update(school_id: str, user: dict, body: TransportUpdateCreateIn) -> TransportUpdateOut:
    if not _is_manager(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    client = get_client()
    row = body.model_dump()
    row["school_id"] = school_id
    row["created_by_user_id"] = user["id"]
    res = await client.table("transport_updates").insert(row).execute()
    if not res.data:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Failed to create update")
    out = await list_updates(school_id, user, limit=1)
    for u in out:
        if u.id == res.data[0]["id"]:
            return u
    user_map = await _user_name_map([user["id"]])
    return TransportUpdateOut(
        id=res.data[0]["id"],
        school_id=res.data[0]["school_id"],
        route_id=res.data[0].get("route_id"),
        title=res.data[0]["title"],
        body=res.data[0].get("body"),
        update_type=res.data[0].get("update_type", "announcement"),
        created_by_user_id=user["id"],
        created_by_name=user_map.get(user["id"], ""),
        created_at=res.data[0].get("created_at"),
    )


async def delete_update(school_id: str, update_id: str, user: dict) -> None:
    if not _is_admin(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient permissions")
    client = get_client()
    await client.table("transport_updates").delete().eq("school_id", school_id).eq("id", update_id).execute()


# ---------------------------------------------------------------------------
# Student/parent "my transport"
# ---------------------------------------------------------------------------
async def get_my_transport(school_id: str, user: dict) -> MyTransportOut:
    if not _is_student_or_parent(user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only students and parents can access this endpoint")
    student_id = await _resolve_student_id(school_id, user)
    if not student_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No linked student found")
    client = get_client()
    ares = (
        await client.table("transport_assignments")
        .select(_ASSIGN_COLS)
        .eq("school_id", school_id)
        .eq("student_id", student_id)
        .order("created_at", desc=True)
        .limit(1)
        .execute()
    )
    if not ares.data:
        return MyTransportOut(status="not_assigned")
    arow = ares.data[0]
    student_map = await _student_name_map(school_id, [student_id])
    route_map = await _route_name_map(school_id, [arow["route_id"]] if arow.get("route_id") else [])
    vehicle_map = await _vehicle_name_map(school_id, [arow["vehicle_id"]] if arow.get("vehicle_id") else [])
    stop_map = await _stop_name_map(school_id, [arow["pickup_stop_id"], arow["drop_stop_id"]] if (arow.get("pickup_stop_id") or arow.get("drop_stop_id")) else [])
    assignment = await _enrich_assignment(school_id, arow, student_map, route_map, vehicle_map, stop_map)
    route: Optional = None
    vehicle: Optional = None
    driver_name: Optional[str] = None
    if arow.get("route_id"):
        try:
            route = await get_route(school_id, arow["route_id"], user)
        except HTTPException:
            route = None
    if arow.get("vehicle_id"):
        try:
            vehicle = await get_vehicle(school_id, arow["vehicle_id"], user)
        except HTTPException:
            vehicle = None
    if route and route.driver_name:
        driver_name = route.driver_name
    status_map = {
        "active": "active",
        "pending": "pending",
        "inactive": "not_assigned",
        "temporarily_unavailable": "temporarily_unavailable",
    }
    return MyTransportOut(
        status=status_map.get(assignment.status, "not_assigned"),
        assignment=assignment,
        route=route,
        vehicle=vehicle,
        driver_name=driver_name,
    )
