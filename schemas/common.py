"""Shared constants and small response helpers."""

# Roles supported across the application. `super_admin` is a cross-tenant
# override role used internally for elevated access checks.
ROLES = [
    "super_admin",
    "developer",
    "school_admin",
    "principal",
    "vice_principal",
    "teacher",
    "student",
    "parent",
    "accountant",
    "librarian",
    "receptionist",
    "transport_manager",
    "hostel_manager",
    "school_doctor",
]

# Roles permitted to authenticate via the login flow.
# `super_admin` and `developer` use dedicated login endpoints.
LOGIN_ROLES = [r for r in ROLES if r not in ("super_admin", "developer")]
