"""Seed demo transport data for the demo school (KCPSCH).

Run:  .venv/bin/python seed_transport_demo.py
Uses SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY from .env.
Inserts: driver+attendant, a tracked bus, one route with stops,
student assignments, a pending request, updates, and a live GPS fix.
Safe to re-run — reuses existing demo rows instead of duplicating.
"""
import asyncio
import random
import sys
from datetime import date, timedelta

from database import init_supabase

# Demo positions — a plausible town center; adjust if needed.
BASE_LAT, BASE_LNG = 28.6139, 77.2090

STOPS = [
    ("Main Gate", "07:15", "16:05", "School main entrance"),
    ("Central Market", "07:25", "15:55", "Near clock tower"),
    ("Green Park Colony", "07:35", "15:45", "Block C gate"),
    ("Riverside Chowk", "07:50", "15:30", "Bus stand"),
]


async def main() -> None:
    client = await init_supabase()

    sres = (
        await client.table("schools")
        .select("id,school_name,institution_code")
        .eq("institution_code", "KCPSCH")
        .execute()
    )
    if not sres.data:
        print("School KCPSCH not found. Schools:")
        all_s = await client.table("schools").select("id,school_name,institution_code").limit(50).execute()
        for s in all_s.data or []:
            print(" -", s.get("school_name"), s.get("institution_code"), s.get("id"))
        sys.exit(1)
    school = sres.data[0]
    sid = school["id"]
    print(f"School: {school['school_name']} ({sid})")

    vchk = (
        await client.table("transport_vehicles")
        .select("id")
        .eq("school_id", sid)
        .eq("vehicle_number", "BUS-101")
        .execute()
    )
    if vchk.data:
        # Resume mode — reuse existing demo rows.
        v = vchk.data[0]
        d = (
            await client.table("transport_staff")
            .select("id")
            .eq("school_id", sid)
            .eq("role", "driver")
            .limit(1)
            .execute()
        ).data[0]
        r = (
            await client.table("transport_routes")
            .select("id")
            .eq("school_id", sid)
            .eq("vehicle_id", v["id"])
            .limit(1)
            .execute()
        ).data[0]
        stop_rows = (
            await client.table("transport_route_stops")
            .select("id")
            .eq("route_id", r["id"])
            .order("stop_order")
            .execute()
        ).data or []
        stop_ids = [s["id"] for s in stop_rows]
        print("Demo bus already exists — resuming with assignments/request/updates/location.")
    else:
        # --- Staff ---
        d = (
            await client.table("transport_staff")
            .insert({
                "school_id": sid,
                "full_name": "Ramesh Kumar",
                "role": "driver",
                "mobile": "9876543210",
                "license_no": "DL-0420" + str(random.randint(1000, 9999)),
                "license_expiry": (date.today() + timedelta(days=400)).isoformat(),
                "employee_no": "DRV-01",
                "status": "assigned",
            })
            .execute()
        ).data[0]
        a = (
            await client.table("transport_staff")
            .insert({
                "school_id": sid,
                "full_name": "Sunita Devi",
                "role": "attendant",
                "mobile": "9876543211",
                "employee_no": "ATT-01",
                "status": "assigned",
            })
            .execute()
        ).data[0]
        print(f"Staff: {d['full_name']} (driver), {a['full_name']} (attendant)")

        # --- Vehicle (driver's-phone GPS tracking) ---
        v = (
            await client.table("transport_vehicles")
            .insert({
                "school_id": sid,
                "vehicle_number": "BUS-101",
                "vehicle_type": "bus",
                "capacity": 40,
                "driver_staff_id": d["id"],
                "attendant_staff_id": a["id"],
                "status": "on_route",
                "maintenance_status": "ok",
                "tracking_source": "phone",
                "notes": "Demo bus — morning pickup route",
            })
            .execute()
        ).data[0]
        print(f"Vehicle: {v['vehicle_number']}")

        # --- Route + stops ---
        r = (
            await client.table("transport_routes")
            .insert({
                "school_id": sid,
                "name": "Route 1 — City North",
                "route_code": "R1",
                "vehicle_id": v["id"],
                "driver_staff_id": d["id"],
                "status": "active",
                "pickup_start": "07:15",
                "drop_end": "16:05",
                "notes": "Demo route",
            })
            .execute()
        ).data[0]
        await client.table("transport_vehicles").update({"route_id": r["id"]}).eq("id", v["id"]).execute()

        stop_ids = []
        for i, (name, pickup, drop, landmark) in enumerate(STOPS):
            srow = (
                await client.table("transport_route_stops")
                .insert({
                    "school_id": sid,
                    "route_id": r["id"],
                    "name": name,
                    "stop_order": i,
                    "pickup_time": pickup,
                    "drop_time": drop,
                    "landmark": landmark,
                })
                .execute()
            ).data[0]
            stop_ids.append(srow["id"])
        print(f"Route: {r['name']} with {len(stop_ids)} stops")

    # --- Assign students (first few students of this school) ---
    studs = (
        await client.table("students")
        .select("id,user_id")
        .eq("school_id", sid)
        .limit(6)
        .execute()
    ).data or []
    assigned = 0
    for i, st in enumerate(studs):
        try:
            await client.table("transport_assignments").insert({
                "school_id": sid,
                "student_id": st["id"],
                "route_id": r["id"],
                "vehicle_id": v["id"],
                "pickup_stop_id": stop_ids[min(i + 1, len(stop_ids) - 1)] if stop_ids else None,
                "drop_stop_id": stop_ids[min(i + 1, len(stop_ids) - 1)] if stop_ids else None,
                "pickup_time": STOPS[min(i + 1, len(STOPS) - 1)][1],
                "drop_time": STOPS[min(i + 1, len(STOPS) - 1)][2],
                "status": "active",
                "effective_from": date.today().isoformat(),
            }).execute()
            assigned += 1
        except Exception as exc:  # noqa: BLE001
            print(f"  assignment skipped for {st['id']}: {exc}")
    print(f"Assignments: {assigned} students")

    # --- admin user for requester/created_by ---
    admin = (
        await client.table("users")
        .select("id")
        .eq("school_id", sid)
        .eq("role", "school_admin")
        .limit(1)
        .execute()
    ).data
    uid = admin[0]["id"] if admin else None

    # --- One pending request (route change) ---
    if studs:
        try:
            await client.table("transport_requests").insert({
                "school_id": sid,
                "student_id": studs[0]["id"],
                "requester_user_id": studs[0].get("user_id") or uid,
                "request_type": "route_change",
                "reason": "We moved to Green Park Colony — requesting pickup from the new stop.",
                "preferred_route_id": r["id"],
                "status": "pending",
                "effective_date": (date.today() + timedelta(days=7)).isoformat(),
            }).execute()
            print("Request: pending route_change")
        except Exception as exc:  # noqa: BLE001
            print(f"  request skipped: {exc}")

    # --- Updates / announcements ---
    for title, body_, utype in [
        ("Bus BUS-101 on time", "All pickups running on schedule today.", "announcement"),
        ("Slight delay — Route 1", "Bus is running ~10 minutes late due to traffic near Central Market.", "delay"),
    ]:
        try:
            await client.table("transport_updates").insert({
                "school_id": sid,
                "route_id": r["id"] if "Route 1" in title else None,
                "title": title,
                "body": body_,
                "update_type": utype,
                "created_by_user_id": uid,
            }).execute()
        except Exception as exc:  # noqa: BLE001
            print(f"  update skipped: {exc}")
    print("Updates: posted")

    # --- Live GPS fix so the tracker map shows the bus ---
    await client.table("transport_vehicle_locations").upsert(
        {
            "school_id": sid,
            "vehicle_id": v["id"],
            "latitude": BASE_LAT,
            "longitude": BASE_LNG,
            "speed": 9.5,
            "heading": 128,
            "source": "phone",
            "updated_by_user_id": uid,
        },
        on_conflict="vehicle_id",
    ).execute()
    print("Location: demo GPS fix stored")

    print("\nDone — Overview stats, Vehicles, Routes, Students, Requests and live tracking now show demo data.")


if __name__ == "__main__":
    asyncio.run(main())
