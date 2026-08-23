"""Apply SQL migrations when DATABASE_URL is set.

Usage (from backend/):
    DATABASE_URL='postgresql://postgres:PASSWORD@db.PROJECT_REF.supabase.co:5432/postgres' python migrate.py

Find the connection string in Supabase → Project Settings → Database → Connection string (URI).
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
MIGRATION_ORDER = [
    "001_initial_schema.sql",
    "003_erp_v2.sql",
    "004_academic_tables.sql",
    "005_academic_unique_constraints.sql",
    "006_student_login_password.sql",
    "007_student_pen_document.sql",
    "008_student_documents.sql",
    "009_student_alternate_mobile.sql",
    "010_teacher_documents.sql",
    "011_gallery.sql",
    "012_staff_attendance_retention.sql",
    "013_expense_transactions.sql",
    "014_expense_savings.sql",
    "015_expense_savings_sort_order.sql",
    "016_expense_retention_policy.sql",
    "017_announcement_attachments.sql",
    "018_announcement_recipients_list.sql",
    "019_announcement_retention_policy.sql",
    "020_school_and_period_timing.sql",
    "021_one_class_per_period_timetable.sql",
    "022_class_section_period_assignments.sql",
    "023_school_profile_fields.sql",
    "024_school_calendar_events.sql",
    "025_teacher_substitute_assignments.sql",
    "026_teacher_substitute_day_of_week.sql",
    "027_class_section_period_day_of_week.sql",
    "028_message_recipient.sql",
    "029_message_media.sql",
    "030_message_retention_policy.sql",
    "031_message_file_media.sql",
    "032_message_hidden_for.sql",
    "033_school_open_on_sunday.sql",
    "034_student_aadhar_category.sql",
    "035_class_section_fees.sql",
    "036_school_payment_gateways.sql",
    "037_payment_gateway_other.sql",
    "038_fee_payment_verification.sql",
    "039_announcement_class_audience.sql",
    "040_fee_receipts.sql",
    "041_school_established_date.sql",
    "042_student_transport.sql",
    "043_school_admin_contact.sql",
    "044_homework_retention_and_fields.sql",
    "045_homework_assigned_by_user.sql",
    "046_message_group_id.sql",
    "047_student_approval_status.sql",
    "048_library.sql",
    "049_teacher_medical.sql",
    "050_teacher_medical_visits.sql",
    "051_syllabus.sql",
    "052_syllabus_chapter_completed.sql",
    "053_leave_requests.sql",
    "054_student_settings.sql",
    "055_achievements.sql",
    "055_leave_requests_cancel_and_retention.sql",
    "056_achievements_pin.sql",
    "057_appointments.sql",
    "058_school_medical_visits.sql",
    "059_free_trial.sql",
    "060_school_feed.sql",
    "061_student_medical.sql",
    "062_developer_user.sql",
    "063_help_chat.sql",
    "064_developer_notes.sql",
]


async def run_migrations(database_url: str) -> None:
    try:
        import asyncpg
    except ImportError as exc:
        raise SystemExit("Install asyncpg first: pip install asyncpg") from exc

    print("DATABASE_URL:", repr(database_url))

    from urllib.parse import urlparse
    print("HOST:", urlparse(database_url).hostname)

    conn = await asyncpg.connect(database_url)
    try:
        for name in MIGRATION_ORDER:
            path = MIGRATIONS_DIR / name
            if not path.exists():
                print(f"skip missing {name}")
                continue
            sql = path.read_text(encoding="utf-8")
            print(f"applying {name} ...")
            try:
                await conn.execute(sql)
                print(f"ok {name}")
            except Exception as exc:
                print(f"FAILED {name}: {exc}", file=sys.stderr)
                raise
    finally:
        await conn.close()


def main() -> None:
    from config import get_settings

    settings = get_settings()
    database_url = getattr(settings, "database_url", "") or ""
    if not database_url:
        raise SystemExit(
            "Set DATABASE_URL in backend/.env (Supabase → Settings → Database → URI), then re-run."
        )
    asyncio.run(run_migrations(database_url))


if __name__ == "__main__":
    main()
