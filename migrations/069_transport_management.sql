-- Transport Management system: vehicles, routes, stops, drivers/staff,
-- student assignments, transport requests, and operational updates.
-- All rows are scoped by school_id for multi-tenant isolation.

-- ---------------------------------------------------------------------------
-- Transport staff (drivers / attendants / helpers)
-- ---------------------------------------------------------------------------
create table if not exists transport_staff (
    id              uuid primary key default gen_random_uuid(),
    school_id       uuid not null references schools (id) on delete cascade,
    user_id         uuid references users (id) on delete set null,
    full_name       text not null,
    role            text not null default 'driver',  -- driver | attendant | helper
    mobile          text,
    email           text,
    license_no      text,
    license_expiry  date,
    employee_no     text,
    status          text not null default 'available', -- available | assigned | on_leave | inactive
    notes           text,
    is_active       boolean not null default true,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);
create index if not exists idx_transport_staff_school on transport_staff (school_id);
create index if not exists idx_transport_staff_status on transport_staff (school_id, status);
create index if not exists idx_transport_staff_role on transport_staff (school_id, role);

-- ---------------------------------------------------------------------------
-- Routes (created before vehicles to satisfy FK direction; vehicle link added later)
-- ---------------------------------------------------------------------------
create table if not exists transport_routes (
    id              uuid primary key default gen_random_uuid(),
    school_id       uuid not null references schools (id) on delete cascade,
    name            text not null,
    route_code      text,                              -- human-readable identifier
    vehicle_id      uuid,                              -- FK added below (circular with vehicles)
    driver_staff_id uuid references transport_staff (id) on delete set null,
    status          text not null default 'scheduled', -- scheduled | active | completed | delayed | cancelled | inactive
    pickup_start    text,                              -- HH:MM
    drop_end        text,                              -- HH:MM
    is_active       boolean not null default true,
    notes           text,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),
    unique (school_id, route_code)
);
create index if not exists idx_transport_routes_school on transport_routes (school_id);
create index if not exists idx_transport_routes_status on transport_routes (school_id, status);
create index if not exists idx_transport_routes_vehicle on transport_routes (school_id, vehicle_id);

-- ---------------------------------------------------------------------------
-- Vehicles
-- ---------------------------------------------------------------------------
create table if not exists transport_vehicles (
    id                  uuid primary key default gen_random_uuid(),
    school_id           uuid not null references schools (id) on delete cascade,
    vehicle_number      text not null,
    vehicle_type        text not null default 'bus',  -- bus | van | car | mini_bus | other
    capacity            integer not null default 30 check (capacity > 0),
    driver_staff_id     uuid references transport_staff (id) on delete set null,
    attendant_staff_id  uuid references transport_staff (id) on delete set null,
    route_id            uuid references transport_routes (id) on delete set null,
    status              text not null default 'active',  -- active | inactive | on_route | under_maintenance | unavailable
    maintenance_status  text not null default 'ok',      -- ok | needs_attention | under_repair
    registration_expiry date,
    insurance_expiry    date,
    notes               text,
    is_archived         boolean not null default false,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now(),
    unique (school_id, vehicle_number)
);
create index if not exists idx_transport_vehicles_school on transport_vehicles (school_id);
create index if not exists idx_transport_vehicles_status on transport_vehicles (school_id, status);
create index if not exists idx_transport_vehicles_route on transport_vehicles (school_id, route_id);

-- Now add the routes -> vehicles FK (was deferred due to circular reference).
do $$
begin
    if not exists (
        select 1 from information_schema.table_constraints
        where constraint_name = 'fk_transport_routes_vehicle'
          and table_name = 'transport_routes'
    ) then
        alter table transport_routes
            add constraint fk_transport_routes_vehicle
            foreign key (vehicle_id) references transport_vehicles (id) on delete set null;
    end if;
end $$;

-- ---------------------------------------------------------------------------
-- Route stops (ordered)
-- ---------------------------------------------------------------------------
create table if not exists transport_route_stops (
    id          uuid primary key default gen_random_uuid(),
    school_id   uuid not null references schools (id) on delete cascade,
    route_id    uuid not null references transport_routes (id) on delete cascade,
    name        text not null,
    stop_order  integer not null default 0,
    pickup_time text,   -- HH:MM
    drop_time   text,   -- HH:MM
    landmark    text,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);
create index if not exists idx_transport_route_stops_route on transport_route_stops (route_id, stop_order);
create index if not exists idx_transport_route_stops_school on transport_route_stops (school_id);

-- ---------------------------------------------------------------------------
-- Student transport assignments (one active assignment per student)
-- ---------------------------------------------------------------------------
create table if not exists transport_assignments (
    id              uuid primary key default gen_random_uuid(),
    school_id       uuid not null references schools (id) on delete cascade,
    student_id      uuid not null references students (id) on delete cascade,
    route_id        uuid references transport_routes (id) on delete set null,
    vehicle_id      uuid references transport_vehicles (id) on delete set null,
    pickup_stop_id  uuid references transport_route_stops (id) on delete set null,
    drop_stop_id    uuid references transport_route_stops (id) on delete set null,
    pickup_time     text,
    drop_time       text,
    status          text not null default 'active',  -- active | pending | inactive | temporarily_unavailable
    effective_from  date,
    effective_to    date,
    notes           text,
    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now()
);
create index if not exists idx_transport_assignments_school on transport_assignments (school_id);
create index if not exists idx_transport_assignments_student on transport_assignments (student_id);
create index if not exists idx_transport_assignments_route on transport_assignments (school_id, route_id);
create index if not exists idx_transport_assignments_vehicle on transport_assignments (school_id, vehicle_id);
create index if not exists idx_transport_assignments_status on transport_assignments (school_id, status);
-- Prevent duplicate active assignments per student.
create unique index if not exists uq_transport_assignments_active_student
    on transport_assignments (school_id, student_id)
    where status = 'active';

-- ---------------------------------------------------------------------------
-- Transport requests (student/parent -> admin/manager)
-- ---------------------------------------------------------------------------
create table if not exists transport_requests (
    id                  uuid primary key default gen_random_uuid(),
    school_id           uuid not null references schools (id) on delete cascade,
    student_id          uuid references students (id) on delete cascade,
    requester_user_id   uuid not null references users (id) on delete cascade,
    request_type        text not null,  -- new_service | route_change | pickup_stop_change | drop_stop_change | cancellation
    reason              text,
    preferred_route_id  uuid references transport_routes (id) on delete set null,
    preferred_stop_id   uuid references transport_route_stops (id) on delete set null,
    effective_date      date,
    status              text not null default 'pending',  -- pending | approved | rejected | completed
    response_note       text,
    decided_by_user_id  uuid references users (id) on delete set null,
    decided_at          timestamptz,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);
create index if not exists idx_transport_requests_school on transport_requests (school_id);
create index if not exists idx_transport_requests_status on transport_requests (school_id, status);
create index if not exists idx_transport_requests_requester on transport_requests (requester_user_id);
create index if not exists idx_transport_requests_student on transport_requests (student_id);

-- ---------------------------------------------------------------------------
-- Transport updates / announcements (scoped to route or school-wide)
-- ---------------------------------------------------------------------------
create table if not exists transport_updates (
    id          uuid primary key default gen_random_uuid(),
    school_id   uuid not null references schools (id) on delete cascade,
    route_id    uuid references transport_routes (id) on delete cascade,
    vehicle_id  uuid references transport_vehicles (id) on delete set null,
    title       text not null,
    body        text,
    update_type text not null default 'announcement',  -- announcement | delay | cancellation | vehicle_change | timing_change
    created_by_user_id uuid references users (id) on delete set null,
    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now()
);
create index if not exists idx_transport_updates_school on transport_updates (school_id);
create index if not exists idx_transport_updates_route on transport_updates (route_id);
create index if not exists idx_transport_updates_created on transport_updates (school_id, created_at desc);
