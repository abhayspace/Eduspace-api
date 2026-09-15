"""Reset a single student's password to a random 8-digit number.

Updates both login_password (plaintext for admin visibility) and password_hash (bcrypt)
in the users table for the student with the given admission number in the given school.

Usage (from backend/):
    DATABASE_URL='postgresql://postgres:PASSWORD@db.PROJECT_REF.supabase.co:5432/postgres' \
    python reset_student_password.py --school KSHCNV --admission 1576
"""
import argparse
import asyncio
import secrets
import sys

import bcrypt


def generate_8_digit_password() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(8))


async def reset_student_password(
    database_url: str,
    school_code: str,
    admission_no: str,
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

        # Find the student by admission_no within the school
        row = await conn.fetchrow(
            """
            SELECT u.id, u.full_name, u.email, u.admission_no, u.user_code
            FROM users u
            JOIN students s ON s.user_id = u.id
            WHERE s.school_id = $1
              AND s.approval_status = 'approved'
              AND u.admission_no = $2
            """,
            school_id,
            admission_no,
        )
        if not row:
            print(
                f"No approved student with admission number '{admission_no}' found in school '{school_code}'",
                file=sys.stderr,
            )
            sys.exit(1)

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

        print(f"\nPassword reset successful!")
        print(f"  Name:           {row['full_name']}")
        print(f"  Admission No:   {row['admission_no']}")
        print(f"  Email:          {row['email']}")
        print(f"  User Code:      {row['user_code']}")
        print(f"  New Password:   {pw}")
        print(f"\nThe student will be prompted to change their password on next login.")
    finally:
        await conn.close()


def main() -> None:
    import os

    parser = argparse.ArgumentParser(
        description="Reset a single student's password to a random 8-digit number."
    )
    parser.add_argument("--school", required=True, help="School institution_code (e.g., KSHCNV)")
    parser.add_argument("--admission", required=True, help="Student admission number (e.g., 1576)")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print(
            "Set DATABASE_URL env var (Supabase → Settings → Database → URI)",
            file=sys.stderr,
        )
        sys.exit(1)

    asyncio.run(
        reset_student_password(database_url, args.school, args.admission)
    )


if __name__ == "__main__":
    main()
