"""Seed demo complaints + behaviour records for the demo school (KCPSCH).

Run:  .venv/bin/python seed_complaints_demo.py
Safe to re-run — skips if demo complaints already exist.
"""
import asyncio
import sys
import uuid
from datetime import date, timedelta

from database import init_supabase

SID = "1fc6b6f4-0d2a-4ecf-91ff-546c77a860c6"  # K.C.Public School


async def main() -> None:
    client = await init_supabase()

    existing = await client.table("complaints").select("id", count="exact").eq("school_id", SID).execute()
    if (existing.count or 0) >= 3:
        print("Demo complaints already exist — skipping.")
        return

    studs = (
        await client.table("students")
        .select("id,user_id,class_id,section_id")
        .eq("school_id", SID)
        .limit(6)
        .execute()
    ).data or []
    if not studs:
        print("No students found for KCPSCH")
        sys.exit(1)

    # student names live on users; class/section names on their tables
    user_ids = [s["user_id"] for s in studs if s.get("user_id")]
    users = (
        await client.table("users").select("id,full_name").in_("id", user_ids).execute()
    ).data or []
    uname = {u["id"]: u.get("full_name") or "Student" for u in users}

    cls = (
        await client.table("classes").select("id,name").eq("school_id", SID).execute()
    ).data or []
    cname = {c["id"]: c.get("name") or "" for c in cls}
    secs = (
        await client.table("sections").select("id,name").eq("school_id", SID).execute()
    ).data or []
    sname = {s["id"]: s.get("name") or "" for s in secs}

    teacher = (
        await client.table("users")
        .select("id,full_name")
        .eq("school_id", SID)
        .eq("role", "teacher")
        .limit(1)
        .execute()
    ).data
    admin = (
        await client.table("users")
        .select("id,full_name")
        .eq("school_id", SID)
        .eq("role", "school_admin")
        .limit(1)
        .execute()
    ).data
    teacher_id, teacher_name = (teacher[0]["id"], teacher[0]["full_name"]) if teacher else (None, "Class Teacher")
    admin_id, admin_name = (admin[0]["id"], admin[0]["full_name"]) if admin else (None, "School Admin")

    def stu(i: int) -> dict:
        s = studs[i % len(studs)]
        return {
            "student_id": s["id"],
            "student_name": uname.get(s.get("user_id"), "Student"),
            "class_name": cname.get(s.get("class_id"), ""),
            "section_name": sname.get(s.get("section_id"), ""),
        }

    # --- Complaints ---
    complaints = [
        dict(
            title="Water cooler not working on 2nd floor",
            description="The water cooler near the science lab has been leaking for two days. Students have to go downstairs during break.",
            category="other", severity="low", status="pending",
            submitted_by_user_id=teacher_id, submitted_by_name=teacher_name, submitted_by_role="teacher",
            **{k: stu(0)[k] for k in ("student_id", "student_name")},
        ),
        dict(
            title="Bullying reported in playground",
            description="A group of senior students were seen pushing younger students near the swings during lunch break.",
            category="bullying", severity="high", status="under_review",
            is_anonymous=True, submitted_by_name="Anonymous", submitted_by_role="parent",
            **{k: stu(1)[k] for k in ("student_id", "student_name")},
            assigned_to_user_id=admin_id, assigned_to_name=admin_name or "",
        ),
        dict(
            title="Homework load too heavy for Class 8",
            description="Students are getting 4+ hours of homework daily across subjects. Request to balance the schedule.",
            category="academic", severity="medium", status="resolved",
            submitted_by_user_id=admin_id, submitted_by_name=admin_name or "Parent", submitted_by_role="parent",
            **{k: stu(2)[k] for k in ("student_id", "student_name")},
            resolution_notes="Discussed with subject teachers; homework timetable adjusted from next week.",
        ),
        dict(
            title="Bus arrives late on Route 1",
            description="BUS-101 has been reaching Green Park Colony ~15 min late this week.",
            category="attendance", severity="medium", status="pending",
            submitted_by_user_id=admin_id, submitted_by_name=admin_name or "Parent", submitted_by_role="parent",
            **{k: stu(3)[k] for k in ("student_id", "student_name")},
        ),
    ]
    for i, c in enumerate(complaints):
        row = {
            "id": str(uuid.uuid4()),
            "school_id": SID,
            "incident_date": (date.today() - timedelta(days=i + 1)).isoformat(),
            **c,
        }
        await client.table("complaints").insert(row).execute()
        await client.table("complaint_activity").insert({
            "school_id": SID,
            "complaint_id": row["id"],
            "action": "created",
            "description": "Complaint created",
            "actor_user_id": c.get("submitted_by_user_id"),
            "actor_name": c.get("submitted_by_name") or "",
            "actor_role": c.get("submitted_by_role") or "",
        }).execute()
    print(f"Complaints: {len(complaints)} created")

    # --- Behaviour records ---
    behaviour = [
        dict(type="positive", category="helpful", severity="low",
             description="Helped a new classmate settle in and shared notes after class.",
             recorded_by_user_id=teacher_id, recorded_by_name=teacher_name, recorded_by_role="teacher",
             **stu(0)),
        dict(type="positive", category="participation", severity="low",
             description="Led the science quiz team — excellent teamwork.",
             recorded_by_user_id=teacher_id, recorded_by_name=teacher_name, recorded_by_role="teacher",
             **stu(1)),
        dict(type="negative", category="disruptive", severity="medium",
             description="Talking loudly and disturbing the class during maths period.",
             recorded_by_user_id=teacher_id, recorded_by_name=teacher_name, recorded_by_role="teacher",
             **stu(2)),
        dict(type="negative", category="misbehaviour", severity="high",
             description="Rude behaviour towards the bus attendant during morning pickup.",
             recorded_by_user_id=admin_id, recorded_by_name=admin_name or "Transport Manager", recorded_by_role="school_admin",
             **stu(3)),
    ]
    for i, b in enumerate(behaviour):
        await client.table("behaviour_records").insert({
            "school_id": SID,
            "incident_date": (date.today() - timedelta(days=i)).isoformat(),
            **b,
        }).execute()
    print(f"Behaviour records: {len(behaviour)} created")
    print("Done — Complaints & Behaviour now has demo data.")


if __name__ == "__main__":
    asyncio.run(main())
