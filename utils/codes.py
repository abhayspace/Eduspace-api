"""Generators for institution codes, admin user IDs, and secure temp passwords."""
import re
import secrets
import string

_PW_SPECIAL = "!@#$%*?"

# Common filler words stripped when building an institution code abbreviation.
_FILLER = {
    "the", "a", "an", "and", "of", "for", "in", "at", "to", "on", "by",
    "with", "from", "or", "is", "are", "was", "were", "be", "been", "but",
    "as", "if", "so", "yet",
}


def _initials_from_name(name: str, target_len: int = 6) -> str:
    """Return a meaningful uppercase abbreviation of a school name.

    Strategy:
    1. Strip punctuation, split into words.
    2. Drop common filler words.
    3. Take the first letter of each remaining word → join.
    4. If the result is shorter than target_len, also fill in with consonants
       from the first meaningful word.
    5. Truncate to target_len (max 8 chars).

    Examples:
        Modern School            → MDRSCH   (Modern→MDR, School→SCH)
        Green Valley Public Sch  → GRNVPS
        Delhi Public School      → DLTPS
        St. Xavier School        → STXSCH
    """
    words = [re.sub(r"[^a-zA-Z0-9]", "", w) for w in name.split()]
    words = [w.upper() for w in words if w and w.lower() not in _FILLER and len(w) > 1]
    if not words:
        return "EDU"

    # Take up to 3-char slices from each word (consonant-preferring).
    parts = []
    for w in words:
        # prefer consonants after the first letter
        consonants = w[0] + "".join(c for c in w[1:] if c not in "AEIOU")
        chunk = consonants[:3] if len(consonants) >= 2 else w[:2]
        parts.append(chunk)

    code = "".join(parts)[:target_len]
    # Pad to at least 4 chars if very short
    if len(code) < 4:
        code = (code + words[0])[:target_len]
    return code.upper()


def generate_institution_code(school_name: str) -> str:
    """Return a base institution code from the school name (no uniqueness check)."""
    return _initials_from_name(school_name, target_len=6)


def generate_unique_code_variants(school_name: str):
    """Yield institution code candidates: base, then base + 01, 02, ..."""
    base = generate_institution_code(school_name)
    yield base
    for i in range(1, 100):
        yield f"{base}{i:02d}"


def generate_admin_user_code(existing_count: int) -> str:
    """Return a sequential admin user code: ADM001, ADM002, …"""
    return f"ADM{existing_count + 1:03d}"


def generate_school_login_user_code(existing_count: int) -> str:
    """Return a sequential school login user code: SCH001, SCH002, …"""
    return f"SCH{existing_count + 1:03d}"


_ROLE_PREFIX = {
    "teacher": "TCH",
    "student": "STU",
    "receptionist": "REC",
    "accountant": "ACC",
    "librarian": "LIB",
    "hostel_manager": "HST",
    "transport_manager": "TRN",
    "school_doctor": "DOC",
    "principal": "PRC",
    "vice_principal": "VPC",
}


def generate_user_code(role: str, existing_count: int) -> str:
    """Return a sequential user code for the given role, e.g. TCH001."""
    prefix = _ROLE_PREFIX.get(role, "USR")
    return f"{prefix}{existing_count + 1:03d}"


def generate_employee_no(role: str, existing_count: int) -> str:
    """Return a sequential employee number, e.g. EMP-TCH-001."""
    prefix = _ROLE_PREFIX.get(role, "STF")
    return f"EMP-{prefix}-{existing_count + 1:03d}"


def generate_admission_no(existing_count: int) -> str:
    """Return a sequential admission number: 0001–9999 (4 digits), then 10000+ (5 digits)."""
    next_seq = max(1, existing_count + 1)
    width = 5 if next_seq >= 10000 else 4
    return str(next_seq).zfill(width)


def normalize_admission_no(value: str) -> str:
    """Normalize admission numbers; numeric values are zero-padded per school rules."""
    raw = (value or "").strip()
    if not raw:
        return raw
    if raw.isdigit():
        n = int(raw)
        width = 5 if n >= 10000 else 4
        return str(n).zfill(width)
    return raw.upper()


def generate_temp_password(length: int = 12) -> str:
    """Return a cryptographically secure temporary password.

    Guarantees at least one uppercase, lowercase, digit and special character.
    """
    length = max(10, length)
    alphabet = string.ascii_letters + string.digits + _PW_SPECIAL
    while True:
        pw = "".join(secrets.choice(alphabet) for _ in range(length))
        if (
            any(c.isupper() for c in pw)
            and any(c.islower() for c in pw)
            and any(c.isdigit() for c in pw)
            and any(c in _PW_SPECIAL for c in pw)
        ):
            return pw
