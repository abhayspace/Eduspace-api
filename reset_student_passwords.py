"""Reset all student passwords to random 8-digit numeric strings.

Updates both login_password (plaintext for admin visibility) and password_hash (bcrypt)
in the users table for all approved students.

Usage (from backend/):
    DATABASE_URL='postgresql://postgres:PASSWORD@db.PROJECT_REF.supabase.co:5432/postgres' python reset_student_passwords.py
"""
import asyncio
import secrets
import sys

import bcrypt


def generate_8_digit_password() -> str:
    return "".join(secrets.choice("0123456789") for _ in range(8))


async def reset_passwords(database_url: str) -> None:
    try:
        import asyncpg
    except ImportError:
        print("Install asyncpg first: pip install asyncpg", file=sys.stderr)
        sys.exit(1)

    conn = await asyncpg.connect(database_url)
    try:
        rows = await conn.fetch(
            """
            SELECT u.id
            FROM users u
            JOIN students s ON s.user_id = u.id
            WHERE s.approval_status = 'approved'
            """
        )
        print(f"Found {len(rows)} students to update")

        updated = 0
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
            if updated % 50 == 0:
                print(f"  updated {updated}/{len(rows)}")

        print(f"Done! Updated {updated} student passwords to random 8-digit numbers.")
    finally:
        await conn.close()


def main() -> None:
    import os
    database_url = os.environ.get("DATABASE_URL", "")
    if not database_url:
        print("Set DATABASE_URL env var (Supabase → Settings → Database → URI)", file=sys.stderr)
        sys.exit(1)
    asyncio.run(reset_passwords(database_url))


if __name__ == "__main__":
    main()
