"""Shared pytest fixtures for the EduSpace API integration tests.

These tests run against a live backend instance (default http://127.0.0.1:8001)
backed by the demo seed data in migrations/002_seed_demo.sql.
"""
import os

import pytest
import requests

BASE_URL = (
    os.environ.get("EXPO_PUBLIC_BACKEND_URL")
    or os.environ.get("EDUSPACE_BACKEND_URL")
    or "http://127.0.0.1:8001"
).rstrip("/")

# Demo institution codes seeded by 002_seed_demo.sql.
GF_CODE = "GREEN001"
WL_CODE = "WLAKE001"

# Demo credentials: identifier -> (password, role)
DEMO = {
    "admin": ("ADM001", "Admin123!", "school_admin"),
    "principal": ("PRN001", "Principal123!", "principal"),
    "teacher": ("TCH001", "Teacher123!", "teacher"),
    "student": ("STU001", "Student123!", "student"),
    "parent": ("STU001", "Parent123!", "parent"),
}


@pytest.fixture(scope="session")
def base_url():
    return BASE_URL


@pytest.fixture(scope="session")
def api():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# A second session alias used by the multitenant suite.
@pytest.fixture(scope="session")
def api_session(api):
    return api


def _school_id(api, base_url, code):
    r = api.post(f"{base_url}/api/schools/verify", json={"code": code})
    assert r.status_code == 200, f"verify {code}: {r.status_code} {r.text}"
    return r.json()["id"]


@pytest.fixture(scope="session")
def gf_school_id(api, base_url):
    return _school_id(api, base_url, GF_CODE)


@pytest.fixture(scope="session")
def wl_school_id(api, base_url):
    return _school_id(api, base_url, WL_CODE)


def _login(api, base_url, identifier, password, role, school_id):
    return api.post(
        f"{base_url}/api/auth/login",
        json={
            "identifier": identifier,
            "password": password,
            "role": role,
            "school_id": school_id,
        },
    )


@pytest.fixture(scope="session")
def tokens(api, base_url, gf_school_id):
    out = {}
    for key, (ident, pw, role) in DEMO.items():
        r = _login(api, base_url, ident, pw, role, gf_school_id)
        assert r.status_code == 200, f"login {key}: {r.status_code} {r.text}"
        out[key] = r.json()["access_token"]
    return out


@pytest.fixture
def auth_h(tokens):
    return lambda role: {"Authorization": f"Bearer {tokens[role]}"}
