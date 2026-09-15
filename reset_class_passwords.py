"""Reset all student passwords in a specific class/section to random 8-digit numbers.

Updates both login_password (plaintext for admin visibility) and password_hash (bcrypt)
in the users table for all approved students in the given school, class, and section.

Usage (from backend/):
    DATABASE_URL='postgresql://postgres:PASSWORD@db.PROJECT_REF.supabase.co:5432/postgres' \
    python reset_class_passwords.py --school KSHCNV --class 10 --section A
"""
import argparse
import asyncio
import secrets
import sys

import bcrypt


def generate_8_digit_password() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(8))


async def reset_class_passwords(
    database_url: str,
    school_code: str,
    class_name: str,
    section_name: str,
) -> None:
    try:
        import asyncpg
    except ImportError:
        print("Install asyncpg first: pip install asyncpg", file=sys.stderr)
        sys.exit(1)

    conn = await asyncpg.connect(database_url)
    try:
        # Find the school by institution_code
        school_row = await conn.fetchrow(
            "SELECT id FROM schools WHERE institution_code = $1", school_code
        )
        if not school_row:
            print(f"School with institution_code '{school_code}' not found", file=sys.stderr)
            sys.exit(1)
        school_id = school_row["id"]
        print(f"Found school: {school_code} (id={school_id})")

        # Find the class by name within the school
        class_row = await conn.fetchrow(
            "SELECT id FROM classes WHERE school_id = $1 AND name = $2", school_id, class_name
        )
        if not class_row:
            print(f"Class '{class_name}' not found in school '{school_code}'", file=sys.stderr)
            sys.exit(1)
        class_id = class_row["id"]
        print(f"Found class: {class_name} (id={class_id})")

        # Find the section by name within the class
        section_row = await conn.fetchrow(
            "SELECT id FROM sections WHERE school_id = $1 AND class_id = $2 AND name = $3",
            school_id,
            class_id,
            section_name,
        )
        if not section_row:
            print(
                f"Section '{section_name}' not found for class '{class_name}' in school '{school_code}'",
                file=sys.stderr,
            )
            sys.exit(1)
        section_id = section_row["id"]
        print(f"Found section: {section_name} (id={section_id})")

        # Find all approved students in this class/section
        rows = await conn.fetch(
            """
            SELECT u.id, u.full_name, u.email, u.admission_no, u.user_code
            FROM users u
            JOIN students s ON s.user_id = u.id
            WHERE s.school_id = $1
              AND s.class_id = $2
              AND s.section_id = $3
              AND s.approval_status = 'approved'
            """,
            school_id,
            class_id,
            section_id,
        )
        print(f"\nFound {len(rows)} students in class {class_name}-{section_name} at {school_code}")

        if not rows:
            print("No students to update. Exiting.")
            return

        updated = 0
        print(f"\n{'Name':<30} {'Admission No':<15} {'Email':<40} {'New Password'}")
        print("-" * 100)
        for row in rows:
            pw = generate_8_digit_password()
            pw_hash = bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()
            await conn.execute(
                """
                UPDATE users
                SET login_password = $1, password_hash = $2, must_change_password = true
                WHERE id = $3
                """,
                pw,
                pw_hash,
                row["id"],
            )
            updated += 1
            name = row["full_name"] or ""
            adm = row["admission_no"] or ""
            email = row["email"] or ""
            print(f"{name:<30} {adm:<15} {email:<40} {pw}")

        print(f"\nDone! Updated {updated} student passwords to random 8-digit numbers.")
        print("Students will be prompted to change their password on next login.")
    finally:
        await conn.close()


def main() -> None:
    import os

    parser = argparse.ArgumentParser(
        description="Reset student passwords for a specific class/section to random 8-digit numbers."
    )
    parser.add_argument("--school", required=True, help="School institution_code (e.g., KSHCNV)")
    parser.add_argument("--class", required=True, help="Class name (e.g., 10)")
    parser.add_argument("--section", required=True, help="Section name (e.g., A)")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print(
            "Set DATABASE_URL env var (Supabase → Settings → Database → URI)",
            file=sys.stderr,
        )
        sys.exit(1)

    asyncio.run(
        reset_class_passwords(database_url, args.school, args.class, args.section)
    )


if __name__ == "__main__":
    main()
