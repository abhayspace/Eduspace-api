-- Live bus tracking: per-vehicle GPS source config + latest known location.
-- tracking_source: 'none' | 'phone' (driver app posts GPS) | 'traccar' (GPS device via Traccar) | 'vendor' (other API)
alter table transport_vehicles
    add column if not exists tracking_source text not null default 'none',
    add column if not exists tracker_device_id text;

-- One row per vehicle — the latest reported position (upserted by the
-- driver's phone or synced from an external tracker).
create table if not exists transport_vehicle_locations (
    id uuid primary key default gen_random_uuid(),
    school_id uuid not null references schools(id) on delete cascade,
    vehicle_id uuid not null references transport_vehicles(id) on delete cascade unique,
    latitude double precision not null,
    longitude double precision not null,
    speed double precision,
    heading double precision,
    source text not null default 'phone',
    recorded_at timestamptz not null default now(),
    updated_by_user_id uuid,
    created_at timestamptz not null default now(),
    updated_at timestamptz not null default now()
);

create index if not exists idx_transport_vehicle_locations_school
    on transport_vehicle_locations (school_id, vehicle_id);
