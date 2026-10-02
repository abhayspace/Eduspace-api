"""Fix subject naming for school KSHCNV.

- Removes duplicate/variant subject names and re-points teachers.subjects
  (jsonb string array), class_section_period_assignments (subject_id +
  subject_name), and teacher_substitute_assignments (subject_name) to the
  canonical subject names/ids.
- Ensures canonical subjects exist in the subjects table.

Usage:
    .venv/bin/python fix_kshcnv_subjects.py          # dry run
    APPLY=1 .venv/bin/python fix_kshcnv_subjects.py  # apply
"""
import asyncio
import os
import re
import urllib.parse

import asyncpg
from dotenv import dotenv_values

APPLY = os.environ.get("APPLY") == "1"

# normalized variant -> canonical subject name
VARIANT_MAP = {
    "gk": "General Knowledge",                      # "G. K.", "G.K.", "GK"
    "generalknowledgegk": "General Knowledge",      # "General Knowledge(GK)"
    "environmentalstudiesevs": "Environmental Studies",  # "Environmental Studies (EVS)"
    "evs": "Environmental Studies",                 # "E. V. S."
    "environmentalscience": "Environmental Studies",
    "math": "Mathematics",
    "hindisanskrit": "Hindi / Sanskrit",
    "computergeneralknowledgedrawing": "Computer / General / Drawing",
}

CANONICALS = sorted(set(VARIANT_MAP.values()))


def norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


async def main() -> None:
    cfg = dotenv_values(".env")
    dsn = cfg["DATABASE_URL"]
    u = urllib.parse.urlsplit(dsn)
    qs = urllib.parse.parse_qs(u.query)
    ssl = "require" if qs.get("sslmode", [""])[0] != "disable" else None
    dsn = urllib.parse.urlunsplit((u.scheme, u.netloc, u.path, "", ""))

    conn = await asyncpg.connect(dsn, ssl=ssl)
    try:
        school = await conn.fetchrow(
            "select id, institution_code, school_name from schools "
            "where institution_code ilike 'KSHCNV'"
        )
        if not school:
            print("School KSHCNV not found")
            return
        sid = school["id"]
        print(f"School: {school['school_name']} ({school['institution_code']}) id={sid}")
        print(f"MODE: {'APPLY' if APPLY else 'DRY RUN'}\n")

        subjects = await conn.fetch(
            "select id, name from subjects where school_id=$1 order by name", sid
        )
        print("== subjects table ==")
        for s in subjects:
            tag = "VARIANT" if norm(s["name"]) in VARIANT_MAP and s["name"] not in CANONICALS else ""
            print(f"  {s['name']!r}  {s['id']}  {tag}")

        canon_ids = {s["name"]: s["id"] for s in subjects if s["name"] in CANONICALS}
        variant_rows = [
            s for s in subjects
            if norm(s["name"]) in VARIANT_MAP and s["name"] not in CANONICALS
        ]
        variant_names = {s["name"] for s in variant_rows}
        variant_ids = {s["id"] for s in variant_rows}
        # name -> canonical for matched variant rows
        rename = {s["name"]: VARIANT_MAP[norm(s["name"])] for s in variant_rows}
        id_to_target = {s["id"]: VARIANT_MAP[norm(s["name"])] for s in variant_rows}

        teachers = await conn.fetch(
            "select id, user_id, subjects from teachers where school_id=$1", sid
        )
        print("\n== teachers with variant subjects ==")
        teacher_updates = []
        for t in teachers:
            subs = t["subjects"] or []
            hits = [x for x in subs if norm(str(x)) in VARIANT_MAP and str(x) not in CANONICALS]
            if not hits:
                continue
            new_subs = []
            for x in subs:
                x = str(x)
                target = VARIANT_MAP.get(norm(x))
                if target and x not in CANONICALS:
                    x = target
                if x not in new_subs:
                    new_subs.append(x)
            print(f"  teacher {t['id']}: {subs} -> {new_subs}")
            teacher_updates.append((t["id"], new_subs))

        sched = await conn.fetch(
            "select id, section_id, period_index, day_of_week, subject_id, subject_name "
            "from class_section_period_assignments where school_id=$1", sid
        )
        print("\n== schedule rows with variant subjects ==")
        sched_updates = []
        for r in sched:
            name = r["subject_name"] or ""
            if r["subject_id"] in variant_ids or (norm(name) in VARIANT_MAP and name not in CANONICALS):
                target = id_to_target.get(r["subject_id"]) or rename.get(name) or VARIANT_MAP.get(norm(name))
                if not target:
                    continue
                print(
                    f"  row {r['id']}: {name!r} ({r['day_of_week']} p{r['period_index']}) -> {target!r}"
                )
                sched_updates.append((r["id"], target))

        subs_asg = await conn.fetch(
            "select id, teacher_id, period_index, day_of_week, subject_name "
            "from teacher_substitute_assignments where school_id=$1", sid
        )
        print("\n== substitute assignments with variant subjects ==")
        sub_updates = []
        for r in subs_asg:
            name = r["subject_name"] or ""
            if norm(name) in VARIANT_MAP and name not in CANONICALS:
                target = VARIANT_MAP[norm(name)]
                print(f"  row {r['id']}: {name!r} -> {target!r}")
                sub_updates.append((r["id"], target))

        # also check other text-subject columns for awareness
        homework = await conn.fetch(
            "select id, subject from homework where school_id=$1", sid
        )
        hw_hits = [h for h in homework if norm(h["subject"] or "") in VARIANT_MAP and h["subject"] not in CANONICALS]
        print(f"\n(homework rows with variant subjects: {len(hw_hits)} - not modified)")

        if not APPLY:
            print("\nDry run complete. Re-run with APPLY=1 to apply.")
            return

        async with conn.transaction():
            # ensure canonical subjects exist
            for name in CANONICALS:
                needed = name in rename.values() or name in CANONICALS
                if name not in canon_ids:
                    ins = await conn.fetchrow(
                        "insert into subjects (school_id, name, code) values ($1,$2,$3) returning id",
                        sid, name, name[:3].upper(),
                    )
                    canon_ids[name] = ins["id"]
                    print(f"created subject {name!r}")

            # teachers.subjects jsonb arrays
            for tid, new_subs in teacher_updates:
                import json
                await conn.execute(
                    "update teachers set subjects=$1::jsonb, updated_at=now() where id=$2",
                    json.dumps(new_subs), tid,
                )
                print(f"updated teacher {tid}")

            # schedule rows: re-point subject_id + subject_name
            for rid, target in sched_updates:
                await conn.execute(
                    "update class_section_period_assignments "
                    "set subject_id=$1, subject_name=$2, updated_at=now() where id=$3",
                    canon_ids.get(target), target, rid,
                )
                print(f"updated schedule row {rid} -> {target!r}")

            for rid, target in sub_updates:
                await conn.execute(
                    "update teacher_substitute_assignments set subject_name=$1 where id=$2",
                    target, rid,
                )
                print(f"updated substitute assignment {rid} -> {target!r}")

            # delete variant subject rows
            for s in variant_rows:
                await conn.execute("delete from subjects where id=$1", s["id"])
                print(f"deleted subject {s['name']!r}")

        print("\nDone.")
    finally:
        await conn.close()


asyncio.run(main())
