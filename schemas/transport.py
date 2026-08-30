"""Transport Management — Pydantic schemas."""
from __future__ import annotations

from datetime import date, datetime
from typing import List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums (kept as plain str literals for flexibility across DB/clients)
# ---------------------------------------------------------------------------
VehicleStatus = str  # active | inactive | on_route | under_maintenance | unavailable
MaintenanceStatus = str  # ok | needs_attention | under_repair
RouteStatus = str  # scheduled | active | completed | delayed | cancelled | inactive
StaffRole = str  # driver | attendant | helper
StaffStatus = str  # available | assigned | on_leave | inactive
AssignmentStatus = str  # active | pending | inactive | temporarily_unavailable
RequestType = str  # new_service | route_change | pickup_stop_change | drop_stop_change | cancellation
RequestStatus = str  # pending | approved | rejected | completed
UpdateType = str  # announcement | delay | cancellation | vehicle_change | timing_change


# ---------------------------------------------------------------------------
# Transport staff
# ---------------------------------------------------------------------------
class TransportStaffBase(BaseModel):
    full_name: str
    role: StaffRole = "driver"
    mobile: Optional[str] = None
    email: Optional[str] = None
    license_no: Optional[str] = None
    license_expiry: Optional[date] = None
    employee_no: Optional[str] = None
    status: StaffStatus = "available"
    notes: Optional[str] = None
    is_active: bool = True


class TransportStaffCreateIn(TransportStaffBase):
    pass


class TransportStaffUpdateIn(BaseModel):
    full_name: Optional[str] = None
    role: Optional[StaffRole] = None
    mobile: Optional[str] = None
    email: Optional[str] = None
    license_no: Optional[str] = None
    license_expiry: Optional[date] = None
    employee_no: Optional[str] = None
    status: Optional[StaffStatus] = None
    notes: Optional[str] = None
    is_active: Optional[bool] = None


class TransportStaffOut(BaseModel):
    id: str
    school_id: str
    full_name: str
    role: StaffRole = "driver"
    mobile: Optional[str] = None
    email: Optional[str] = None
    license_no: Optional[str] = None
    license_expiry: Optional[date] = None
    employee_no: Optional[str] = None
    status: StaffStatus = "available"
    notes: Optional[str] = None
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Vehicles
# ---------------------------------------------------------------------------
class TransportVehicleBase(BaseModel):
    vehicle_number: str
    vehicle_type: str = "bus"
    capacity: int = Field(default=30, ge=1)
    driver_staff_id: Optional[str] = None
    attendant_staff_id: Optional[str] = None
    route_id: Optional[str] = None
    status: VehicleStatus = "active"
    maintenance_status: MaintenanceStatus = "ok"
    registration_expiry: Optional[date] = None
    insurance_expiry: Optional[date] = None
    notes: Optional[str] = None


class TransportVehicleCreateIn(TransportVehicleBase):
    pass


class TransportVehicleUpdateIn(BaseModel):
    vehicle_number: Optional[str] = None
    vehicle_type: Optional[str] = None
    capacity: Optional[int] = Field(default=None, ge=1)
    driver_staff_id: Optional[str] = None
    attendant_staff_id: Optional[str] = None
    route_id: Optional[str] = None
    status: Optional[VehicleStatus] = None
    maintenance_status: Optional[MaintenanceStatus] = None
    registration_expiry: Optional[date] = None
    insurance_expiry: Optional[date] = None
    notes: Optional[str] = None
    is_archived: Optional[bool] = None


class TransportVehicleOut(BaseModel):
    id: str
    school_id: str
    vehicle_number: str
    vehicle_type: str = "bus"
    capacity: int = 30
    driver_staff_id: Optional[str] = None
    driver_name: Optional[str] = None
    attendant_staff_id: Optional[str] = None
    attendant_name: Optional[str] = None
    route_id: Optional[str] = None
    route_name: Optional[str] = None
    status: VehicleStatus = "active"
    maintenance_status: MaintenanceStatus = "ok"
    registration_expiry: Optional[date] = None
    insurance_expiry: Optional[date] = None
    notes: Optional[str] = None
    is_archived: bool = False
    assigned_students: int = 0
    available_seats: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Route stops
# ---------------------------------------------------------------------------
class TransportStopBase(BaseModel):
    name: str
    stop_order: int = 0
    pickup_time: Optional[str] = None
    drop_time: Optional[str] = None
    landmark: Optional[str] = None


class TransportStopCreateIn(TransportStopBase):
    pass


class TransportStopOut(BaseModel):
    id: str
    route_id: str
    name: str
    stop_order: int = 0
    pickup_time: Optional[str] = None
    drop_time: Optional[str] = None
    landmark: Optional[str] = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
class TransportRouteBase(BaseModel):
    name: str
    route_code: Optional[str] = None
    vehicle_id: Optional[str] = None
    driver_staff_id: Optional[str] = None
    status: RouteStatus = "scheduled"
    pickup_start: Optional[str] = None
    drop_end: Optional[str] = None
    is_active: bool = True
    notes: Optional[str] = None


class TransportRouteCreateIn(TransportRouteBase):
    stops: List[TransportStopCreateIn] = Field(default_factory=list)


class TransportRouteUpdateIn(BaseModel):
    name: Optional[str] = None
    route_code: Optional[str] = None
    vehicle_id: Optional[str] = None
    driver_staff_id: Optional[str] = None
    status: Optional[RouteStatus] = None
    pickup_start: Optional[str] = None
    drop_end: Optional[str] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None
    stops: Optional[List[TransportStopCreateIn]] = None


class TransportRouteOut(BaseModel):
    id: str
    school_id: str
    name: str
    route_code: Optional[str] = None
    vehicle_id: Optional[str] = None
    vehicle_number: Optional[str] = None
    vehicle_capacity: int = 0
    driver_staff_id: Optional[str] = None
    driver_name: Optional[str] = None
    status: RouteStatus = "scheduled"
    pickup_start: Optional[str] = None
    drop_end: Optional[str] = None
    is_active: bool = True
    notes: Optional[str] = None
    stops: List[TransportStopOut] = Field(default_factory=list)
    assigned_students: int = 0
    available_seats: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Student transport assignments
# ---------------------------------------------------------------------------
class TransportAssignmentBase(BaseModel):
    student_id: str
    route_id: Optional[str] = None
    vehicle_id: Optional[str] = None
    pickup_stop_id: Optional[str] = None
    drop_stop_id: Optional[str] = None
    pickup_time: Optional[str] = None
    drop_time: Optional[str] = None
    status: AssignmentStatus = "active"
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    notes: Optional[str] = None


class TransportAssignmentCreateIn(TransportAssignmentBase):
    pass


class TransportAssignmentUpdateIn(BaseModel):
    route_id: Optional[str] = None
    vehicle_id: Optional[str] = None
    pickup_stop_id: Optional[str] = None
    drop_stop_id: Optional[str] = None
    pickup_time: Optional[str] = None
    drop_time: Optional[str] = None
    status: Optional[AssignmentStatus] = None
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    notes: Optional[str] = None


class TransportAssignmentOut(BaseModel):
    id: str
    school_id: str
    student_id: str
    student_name: str = ""
    class_name: str = ""
    section_name: str = ""
    admission_no: Optional[str] = None
    route_id: Optional[str] = None
    route_name: Optional[str] = None
    vehicle_id: Optional[str] = None
    vehicle_number: Optional[str] = None
    pickup_stop_id: Optional[str] = None
    pickup_stop_name: Optional[str] = None
    drop_stop_id: Optional[str] = None
    drop_stop_name: Optional[str] = None
    pickup_time: Optional[str] = None
    drop_time: Optional[str] = None
    status: AssignmentStatus = "active"
    effective_from: Optional[date] = None
    effective_to: Optional[date] = None
    notes: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Transport requests
# ---------------------------------------------------------------------------
class TransportRequestCreateIn(BaseModel):
    student_id: Optional[str] = None  # inferred for student/parent if absent
    request_type: RequestType
    reason: Optional[str] = None
    preferred_route_id: Optional[str] = None
    preferred_stop_id: Optional[str] = None
    effective_date: Optional[date] = None


class TransportRequestDecideIn(BaseModel):
    status: RequestStatus  # approved | rejected | completed
    response_note: Optional[str] = None


class TransportRequestOut(BaseModel):
    id: str
    school_id: str
    student_id: Optional[str] = None
    student_name: str = ""
    class_name: str = ""
    section_name: str = ""
    requester_user_id: str
    requester_name: str = ""
    request_type: RequestType
    reason: Optional[str] = None
    preferred_route_id: Optional[str] = None
    preferred_route_name: Optional[str] = None
    preferred_stop_id: Optional[str] = None
    preferred_stop_name: Optional[str] = None
    effective_date: Optional[date] = None
    status: RequestStatus = "pending"
    response_note: Optional[str] = None
    decided_by_user_id: Optional[str] = None
    decided_by_name: Optional[str] = None
    decided_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Transport updates / announcements
# ---------------------------------------------------------------------------
class TransportUpdateCreateIn(BaseModel):
    route_id: Optional[str] = None
    vehicle_id: Optional[str] = None
    title: str
    body: Optional[str] = None
    update_type: UpdateType = "announcement"


class TransportUpdateOut(BaseModel):
    id: str
    school_id: str
    route_id: Optional[str] = None
    route_name: Optional[str] = None
    vehicle_id: Optional[str] = None
    vehicle_number: Optional[str] = None
    title: str
    body: Optional[str] = None
    update_type: UpdateType = "announcement"
    created_by_user_id: Optional[str] = None
    created_by_name: Optional[str] = None
    created_at: Optional[datetime] = None


# ---------------------------------------------------------------------------
# Dashboard / analytics
# ---------------------------------------------------------------------------
class TransportDashboardOut(BaseModel):
    total_vehicles: int = 0
    active_vehicles: int = 0
    on_route_vehicles: int = 0
    under_maintenance_vehicles: int = 0
    total_routes: int = 0
    active_routes: int = 0
    total_drivers: int = 0
    total_transport_students: int = 0
    pending_requests: int = 0
    today_scheduled_routes: int = 0


class TransportRouteOccupancyOut(BaseModel):
    route_id: str
    route_name: str
    vehicle_number: Optional[str] = None
    capacity: int = 0
    assigned_students: int = 0
    occupancy_pct: float = 0.0


class TransportAnalyticsOut(BaseModel):
    total_vehicles: int = 0
    active_vehicles: int = 0
    inactive_vehicles: int = 0
    on_route_vehicles: int = 0
    under_maintenance_vehicles: int = 0
    total_routes: int = 0
    active_routes: int = 0
    total_transport_students: int = 0
    avg_capacity_utilization: float = 0.0
    route_occupancy: List[TransportRouteOccupancyOut] = Field(default_factory=list)
    students_per_route: List[TransportRouteOccupancyOut] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Student/parent "my transport" overview
# ---------------------------------------------------------------------------
class MyTransportOut(BaseModel):
    status: str = "not_assigned"  # active | pending | not_assigned | temporarily_unavailable
    assignment: Optional[TransportAssignmentOut] = None
    route: Optional[TransportRouteOut] = None
    vehicle: Optional[TransportVehicleOut] = None
    driver_name: Optional[str] = None
