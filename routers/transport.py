"""Transport Management — router with role-based authorization."""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, status

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
    TransportRouteUpdateIn,
    TransportStaffCreateIn,
    TransportStaffOut,
    TransportStaffUpdateIn,
    TransportUpdateCreateIn,
    TransportUpdateOut,
    TransportVehicleCreateIn,
    TransportVehicleOut,
    TransportVehicleUpdateIn,
)
from services import transport_service as svc
from utils.deps import current_user, require_roles

router = APIRouter(prefix="/transport", tags=["transport"])

_admin_dep = require_roles("school_admin", "principal", "vice_principal", "super_admin")
_manager_dep = require_roles("school_admin", "principal", "vice_principal", "super_admin", "transport_manager")


# ---------------------------------------------------------------------------
# Dashboard / analytics
# ---------------------------------------------------------------------------
@router.get("/dashboard", response_model=TransportDashboardOut)
async def transport_dashboard(user: dict = Depends(_manager_dep)) -> TransportDashboardOut:
    return await svc.get_dashboard(user["school_id"], user)


@router.get("/analytics", response_model=TransportAnalyticsOut)
async def transport_analytics(user: dict = Depends(_admin_dep)) -> TransportAnalyticsOut:
    return await svc.get_analytics(user["school_id"], user)


# ---------------------------------------------------------------------------
# My transport (student/parent)
# ---------------------------------------------------------------------------
@router.get("/my-transport", response_model=MyTransportOut)
async def my_transport(user: dict = Depends(current_user)) -> MyTransportOut:
    return await svc.get_my_transport(user["school_id"], user)


# ---------------------------------------------------------------------------
# Staff
# ---------------------------------------------------------------------------
@router.get("/staff", response_model=List[TransportStaffOut])
async def list_staff(
    role: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    user: dict = Depends(_manager_dep),
) -> List[TransportStaffOut]:
    return await svc.list_staff(user["school_id"], user, role=role, status=status)


@router.post("/staff", response_model=TransportStaffOut, status_code=status.HTTP_201_CREATED)
async def create_staff(
    body: TransportStaffCreateIn,
    user: dict = Depends(_admin_dep),
) -> TransportStaffOut:
    return await svc.create_staff(user["school_id"], user, body)


@router.put("/staff/{staff_id}", response_model=TransportStaffOut)
async def update_staff(
    staff_id: str,
    body: TransportStaffUpdateIn,
    user: dict = Depends(_admin_dep),
) -> TransportStaffOut:
    return await svc.update_staff(user["school_id"], staff_id, user, body)


@router.delete("/staff/{staff_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_staff(staff_id: str, user: dict = Depends(_admin_dep)) -> None:
    await svc.delete_staff(user["school_id"], staff_id, user)


# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------
@router.get("/vehicles", response_model=List[TransportVehicleOut])
async def list_vehicles(
    status: Optional[str] = Query(default=None),
    maintenance_status: Optional[str] = Query(default=None),
    route_id: Optional[str] = Query(default=None),
    include_archived: bool = Query(default=False),
    user: dict = Depends(_manager_dep),
) -> List[TransportVehicleOut]:
    return await svc.list_vehicles(
        user["school_id"], user,
        status=status, maintenance_status=maintenance_status, route_id=route_id,
        include_archived=include_archived,
    )


@router.get("/vehicles/{vehicle_id}", response_model=TransportVehicleOut)
async def get_vehicle(vehicle_id: str, user: dict = Depends(_manager_dep)) -> TransportVehicleOut:
    return await svc.get_vehicle(user["school_id"], vehicle_id, user)


@router.post("/vehicles", response_model=TransportVehicleOut, status_code=status.HTTP_201_CREATED)
async def create_vehicle(
    body: TransportVehicleCreateIn,
    user: dict = Depends(_admin_dep),
) -> TransportVehicleOut:
    return await svc.create_vehicle(user["school_id"], user, body)


@router.put("/vehicles/{vehicle_id}", response_model=TransportVehicleOut)
async def update_vehicle(
    vehicle_id: str,
    body: TransportVehicleUpdateIn,
    user: dict = Depends(_admin_dep),
) -> TransportVehicleOut:
    return await svc.update_vehicle(user["school_id"], vehicle_id, user, body)


@router.put("/vehicles/{vehicle_id}/status", response_model=TransportVehicleOut)
async def update_vehicle_status(
    vehicle_id: str,
    body: dict,
    user: dict = Depends(_manager_dep),
) -> TransportVehicleOut:
    """Operational status update (manager-friendly). Body: {status, maintenance_status?}."""
    return await svc.update_vehicle_status(
        user["school_id"], vehicle_id, user,
        status=body.get("status", ""),
        maintenance_status=body.get("maintenance_status"),
    )


@router.delete("/vehicles/{vehicle_id}", status_code=status.HTTP_204_NO_CONTENT)
async def archive_vehicle(vehicle_id: str, user: dict = Depends(_admin_dep)) -> None:
    await svc.archive_vehicle(user["school_id"], vehicle_id, user)


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@router.get("/routes", response_model=List[TransportRouteOut])
async def list_routes(
    status: Optional[str] = Query(default=None),
    vehicle_id: Optional[str] = Query(default=None),
    driver_staff_id: Optional[str] = Query(default=None),
    include_inactive: bool = Query(default=False),
    user: dict = Depends(_manager_dep),
) -> List[TransportRouteOut]:
    return await svc.list_routes(
        user["school_id"], user,
        status=status, vehicle_id=vehicle_id, driver_staff_id=driver_staff_id,
        include_inactive=include_inactive,
    )


@router.get("/routes/{route_id}", response_model=TransportRouteOut)
async def get_route(route_id: str, user: dict = Depends(current_user)) -> TransportRouteOut:
    return await svc.get_route(user["school_id"], route_id, user)


@router.post("/routes", response_model=TransportRouteOut, status_code=status.HTTP_201_CREATED)
async def create_route(
    body: TransportRouteCreateIn,
    user: dict = Depends(_admin_dep),
) -> TransportRouteOut:
    return await svc.create_route(user["school_id"], user, body)


@router.put("/routes/{route_id}", response_model=TransportRouteOut)
async def update_route(
    route_id: str,
    body: TransportRouteUpdateIn,
    user: dict = Depends(_admin_dep),
) -> TransportRouteOut:
    return await svc.update_route(user["school_id"], route_id, user, body)


@router.put("/routes/{route_id}/status", response_model=TransportRouteOut)
async def update_route_status(
    route_id: str,
    body: dict,
    user: dict = Depends(_manager_dep),
) -> TransportRouteOut:
    """Operational status update (manager-friendly). Body: {status, notes?}."""
    return await svc.update_route_status(
        user["school_id"], route_id, user,
        route_status=body.get("status", ""),
        notes=body.get("notes"),
    )


@router.delete("/routes/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_route(route_id: str, user: dict = Depends(_admin_dep)) -> None:
    await svc.delete_route(user["school_id"], route_id, user)


# ---------------------------------------------------------------------------
# Assignments
# ---------------------------------------------------------------------------
@router.get("/assignments", response_model=List[TransportAssignmentOut])
async def list_assignments(
    class_id: Optional[str] = Query(default=None),
    section_id: Optional[str] = Query(default=None),
    route_id: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    search: Optional[str] = Query(default=None),
    user: dict = Depends(_manager_dep),
) -> List[TransportAssignmentOut]:
    return await svc.list_assignments(
        user["school_id"], user,
        class_id=class_id, section_id=section_id, route_id=route_id,
        status=status, search=search,
    )


@router.post("/assignments", response_model=TransportAssignmentOut, status_code=status.HTTP_201_CREATED)
async def create_assignment(
    body: TransportAssignmentCreateIn,
    user: dict = Depends(_manager_dep),
) -> TransportAssignmentOut:
    return await svc.create_assignment(user["school_id"], user, body)


@router.put("/assignments/{assignment_id}", response_model=TransportAssignmentOut)
async def update_assignment(
    assignment_id: str,
    body: TransportAssignmentUpdateIn,
    user: dict = Depends(_manager_dep),
) -> TransportAssignmentOut:
    return await svc.update_assignment(user["school_id"], assignment_id, user, body)


@router.delete("/assignments/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_assignment(assignment_id: str, user: dict = Depends(_admin_dep)) -> None:
    await svc.delete_assignment(user["school_id"], assignment_id, user)


# ---------------------------------------------------------------------------
# Requests
# ---------------------------------------------------------------------------
@router.get("/requests", response_model=List[TransportRequestOut])
async def list_requests(
    request_type: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=300),
    user: dict = Depends(current_user),
) -> List[TransportRequestOut]:
    return await svc.list_requests(
        user["school_id"], user,
        request_type=request_type, status=status, limit=limit,
    )


@router.post("/requests", response_model=TransportRequestOut, status_code=status.HTTP_201_CREATED)
async def create_request(
    body: TransportRequestCreateIn,
    user: dict = Depends(current_user),
) -> TransportRequestOut:
    return await svc.create_request(user["school_id"], user, body)


@router.put("/requests/{request_id}/decide", response_model=TransportRequestOut)
async def decide_request(
    request_id: str,
    body: TransportRequestDecideIn,
    user: dict = Depends(_manager_dep),
) -> TransportRequestOut:
    return await svc.decide_request(user["school_id"], request_id, user, body)


# ---------------------------------------------------------------------------
# Updates / announcements
# ---------------------------------------------------------------------------
@router.get("/updates", response_model=List[TransportUpdateOut])
async def list_updates(
    route_id: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    user: dict = Depends(current_user),
) -> List[TransportUpdateOut]:
    return await svc.list_updates(user["school_id"], user, route_id=route_id, limit=limit)


@router.post("/updates", response_model=TransportUpdateOut, status_code=status.HTTP_201_CREATED)
async def create_update(
    body: TransportUpdateCreateIn,
    user: dict = Depends(_manager_dep),
) -> TransportUpdateOut:
    return await svc.create_update(user["school_id"], user, body)


@router.delete("/updates/{update_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_update(update_id: str, user: dict = Depends(_admin_dep)) -> None:
    await svc.delete_update(user["school_id"], update_id, user)
