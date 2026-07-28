"""Core API coverage: auth, resources, fees, RBAC."""
from datetime import datetime, timedelta, timezone

from conftest import DEMO, _login


class TestAuth:
    def test_login_returns_token_and_user(self, api, base_url, gf_school_id):
        for key, (ident, pw, role) in DEMO.items():
            r = _login(api, base_url, ident, pw, role, gf_school_id)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body.get("access_token")
            assert body["user"]["role"] == role
            assert body["user"]["school_id"] == gf_school_id

    def test_login_bad_password_401(self, api, base_url, gf_school_id):
        r = _login(api, base_url, "STU001", "wrong-password", "student", gf_school_id)
        assert r.status_code == 401

    def test_login_wrong_school_401(self, api, base_url, wl_school_id):
        r = _login(api, base_url, "STU001", "Student123!", "student", wl_school_id)
        assert r.status_code == 401

    def test_me_without_token_401(self, api, base_url):
        r = api.get(f"{base_url}/api/auth/me")
        assert r.status_code == 401

    def test_me_with_token_200(self, api, base_url, auth_h):
        r = api.get(f"{base_url}/api/auth/me", headers=auth_h("student"))
        assert r.status_code == 200
        assert r.json()["email"] == "student@eduspace.app"


class TestResources:
    def test_announcements_seeded(self, api, base_url, auth_h):
        r = api.get(f"{base_url}/api/announcements", headers=auth_h("student"))
        assert r.status_code == 200
        assert len(r.json()) >= 3

    def test_homework_seeded(self, api, base_url, auth_h):
        r = api.get(f"{base_url}/api/homework", headers=auth_h("student"))
        assert r.status_code == 200
        assert len(r.json()) >= 4

    def test_timetable_grade10a(self, api, base_url, auth_h):
        r = api.get(f"{base_url}/api/timetable", headers=auth_h("student"))
        assert r.status_code == 200
        slots = [s for s in r.json() if s["class_name"] == "Grade 10-A"]
        assert len(slots) >= 13
        # start/end field names are preserved for the frontend.
        assert "start" in slots[0] and "end" in slots[0]

    def test_attendance_me_10(self, api, base_url, auth_h):
        r = api.get(f"{base_url}/api/attendance/me", headers=auth_h("student"))
        assert r.status_code == 200
        assert len(r.json()) == 10

    def test_stats(self, api, base_url, auth_h):
        r = api.get(f"{base_url}/api/stats", headers=auth_h("admin"))
        assert r.status_code == 200
        d = r.json()
        for k in ("users", "teachers", "students", "parents", "announcements", "homework", "pending_fees"):
            assert k in d
        assert d["users"] >= 5


class TestFees:
    def test_fees_list_then_pay(self, api, base_url, auth_h):
        r = api.get(f"{base_url}/api/fees/me", headers=auth_h("student"))
        assert r.status_code == 200
        items = r.json()
        assert len(items) >= 4
        pending = [f for f in items if f["status"] == "pending"]
        assert pending, "no pending fee to pay"
        fee_id = pending[0]["id"]
        pay = api.post(f"{base_url}/api/fees/{fee_id}/pay", headers=auth_h("student"))
        assert pay.status_code == 200, pay.text
        r2 = api.get(f"{base_url}/api/fees/me", headers=auth_h("student"))
        updated = [f for f in r2.json() if f["id"] == fee_id][0]
        assert updated["status"] == "paid"


class TestRBAC:
    def _hw_payload(self, offset_days=30):
        due = (datetime.now(timezone.utc).date() + timedelta(days=offset_days)).isoformat()
        return {
            "subject": "TEST_Subject", "title": "TEST_RBAC_HW",
            "description": "rbac probe", "class_name": "Grade 10-A",
            "due_date": due, "assigned_by": "tester",
        }

    def test_student_cannot_post_homework(self, api, base_url, auth_h):
        r = api.post(f"{base_url}/api/homework", json=self._hw_payload(40), headers=auth_h("student"))
        assert r.status_code == 403, r.text

    def test_teacher_can_post_homework(self, api, base_url, auth_h):
        r = api.post(f"{base_url}/api/homework", json=self._hw_payload(50), headers=auth_h("teacher"))
        assert r.status_code == 200, r.text
        assert r.json()["title"] == "TEST_RBAC_HW"
