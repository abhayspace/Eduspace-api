"""Multi-tenant + chat (REST/WS) + push registration + school registration."""
import asyncio
import json
import uuid

import pytest
import websockets

from conftest import _login


# ---------- Schools (public) ----------
class TestSchools:
    def test_schools_public_no_auth(self, api, base_url, gf_school_id, wl_school_id):
        r = api.get(f"{base_url}/api/schools")
        assert r.status_code == 200, r.text
        ids = {s["id"] for s in r.json()}
        assert {gf_school_id, wl_school_id}.issubset(ids)
        for s in r.json():
            for k in ("id", "name", "short_name", "logo_color"):
                assert k in s

    def test_verify_bad_code_404(self, api, base_url):
        r = api.post(f"{base_url}/api/schools/verify", json={"code": "NOPE-CODE"})
        assert r.status_code == 404


# ---------- Self-service school registration ----------
class TestSchoolRegistration:
    def test_register_school_generates_code_and_hides_password(self, api, base_url):
        school_email = f"school_{uuid.uuid4().hex[:8]}@example.com"
        admin_email = f"admin_{uuid.uuid4().hex[:8]}@example.com"

        for email in (school_email, admin_email):
            api.post(f"{base_url}/api/auth/otp/send", json={"email": email})
            dev = api.post(f"{base_url}/api/auth/otp/dev-read", json={"email": email})
            otp = dev.json().get("otp") if dev.status_code == 200 else None
            if not otp:
                pytest.skip("OTP dev-read unavailable (set LOG_LEVEL=DEBUG for registration tests)")
            verify = api.post(
                f"{base_url}/api/auth/otp/verify",
                json={"email": email, "otp": otp},
            )
            assert verify.status_code == 200, verify.text

        r = api.post(
            f"{base_url}/api/schools/register",
            json={
                "schoolName": "Test Academy",
                "schoolEmail": school_email,
                "schoolPhone": "9876543210",
                "adminFullName": "Test Admin",
                "adminEmail": admin_email,
                "adminMobile": "9123456780",
            },
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["success"] is True
        assert body["institution_code"]
        assert body["school_id"]
        assert "password" not in str(body).lower()

        v = api.post(f"{base_url}/api/schools/verify", json={"code": body["institution_code"]})
        assert v.status_code == 200

    def test_duplicate_school_email_rejected(self, api, base_url):
        school_email = f"dup_{uuid.uuid4().hex[:8]}@example.com"
        admin_email = f"admin_{uuid.uuid4().hex[:8]}@example.com"

        for email in (school_email, admin_email):
            api.post(f"{base_url}/api/auth/otp/send", json={"email": email})
            dev = api.post(f"{base_url}/api/auth/otp/dev-read", json={"email": email})
            otp = dev.json().get("otp") if dev.status_code == 200 else None
            if not otp:
                pytest.skip("OTP dev-read unavailable (set LOG_LEVEL=DEBUG for registration tests)")
            api.post(f"{base_url}/api/auth/otp/verify", json={"email": email, "otp": otp})

        payload = {
            "schoolName": "Dup School",
            "schoolEmail": school_email,
            "schoolPhone": "9876543210",
            "adminFullName": "Dup Admin",
            "adminEmail": admin_email,
            "adminMobile": "9123456780",
        }
        r1 = api.post(f"{base_url}/api/schools/register", json=payload)
        assert r1.status_code == 201, r1.text

        dup_admin = f"admin2_{uuid.uuid4().hex[:8]}@example.com"
        api.post(f"{base_url}/api/auth/otp/send", json={"email": school_email})
        dev = api.post(f"{base_url}/api/auth/otp/dev-read", json={"email": school_email})
        otp = dev.json().get("otp") if dev.status_code == 200 else None
        if otp:
            api.post(f"{base_url}/api/auth/otp/verify", json={"email": school_email, "otp": otp})
        api.post(f"{base_url}/api/auth/otp/send", json={"email": dup_admin})
        dev2 = api.post(f"{base_url}/api/auth/otp/dev-read", json={"email": dup_admin})
        otp2 = dev2.json().get("otp") if dev2.status_code == 200 else None
        if otp2:
            api.post(f"{base_url}/api/auth/otp/verify", json={"email": dup_admin, "otp": otp2})
        r2 = api.post(
            f"{base_url}/api/schools/register",
            json={**payload, "adminEmail": dup_admin},
        )
        assert r2.status_code == 409


# ---------- Multi-tenant auth ----------
class TestTenantAuth:
    def test_student_login_with_correct_school(self, api, base_url, gf_school_id):
        r = _login(api, base_url, "STU001", "Student123!", "student", gf_school_id)
        assert r.status_code == 200, r.text
        assert r.json()["user"]["school_id"] == gf_school_id

    def test_student_login_with_mismatched_school_401(self, api, base_url, wl_school_id):
        r = _login(api, base_url, "STU001", "Student123!", "student", wl_school_id)
        assert r.status_code == 401

    def test_westlake_admin_login(self, api, base_url, wl_school_id):
        r = _login(api, base_url, "ADM001", "Admin123!", "school_admin", wl_school_id)
        assert r.status_code == 200
        assert r.json()["user"]["school_id"] == wl_school_id


@pytest.fixture(scope="module")
def gf_student_token(api, base_url):
    from conftest import GF_CODE
    sid = api.post(f"{base_url}/api/schools/verify", json={"code": GF_CODE}).json()["id"]
    r = _login(api, base_url, "STU001", "Student123!", "student", sid)
    assert r.status_code == 200
    return r.json()["access_token"]


@pytest.fixture(scope="module")
def wl_admin_token(api, base_url):
    from conftest import WL_CODE
    sid = api.post(f"{base_url}/api/schools/verify", json={"code": WL_CODE}).json()["id"]
    r = _login(api, base_url, "ADM001", "Admin123!", "school_admin", sid)
    assert r.status_code == 200
    return r.json()["access_token"]


class TestTenantIsolation:
    def test_stats_differ_per_school(self, api, base_url, gf_student_token, wl_admin_token):
        rg = api.get(f"{base_url}/api/stats", headers={"Authorization": f"Bearer {gf_student_token}"})
        rw = api.get(f"{base_url}/api/stats", headers={"Authorization": f"Bearer {wl_admin_token}"})
        assert rg.status_code == 200 and rw.status_code == 200
        gs, ws = rg.json(), rw.json()
        assert gs["students"] >= 1 and ws["students"] >= 1
        assert gs["announcements"] != ws["announcements"]


# ---------- Messages (REST) ----------
class TestMessagesRest:
    def test_post_and_list_message_school_scoped(self, api, base_url, gf_student_token, wl_admin_token):
        h_gf = {"Authorization": f"Bearer {gf_student_token}"}
        h_wl = {"Authorization": f"Bearer {wl_admin_token}"}
        marker = "TEST_REST_HI_" + uuid.uuid4().hex[:6]
        r = api.post(f"{base_url}/api/messages", json={"text": marker}, headers=h_gf)
        assert r.status_code == 200, r.text
        msg = r.json()
        assert msg["text"] == marker

        r2 = api.get(f"{base_url}/api/messages", headers=h_gf)
        assert msg["id"] in [m["id"] for m in r2.json()]

        r3 = api.get(f"{base_url}/api/messages", headers=h_wl)
        assert msg["id"] not in [m["id"] for m in r3.json()], "GF message leaked to WL"


# ---------- Push registration ----------
class TestPushRegister:
    def test_register_push_returns_201(self, api, base_url, gf_student_token):
        me = api.get(f"{base_url}/api/auth/me", headers={"Authorization": f"Bearer {gf_student_token}"})
        user_id = me.json()["id"]
        r = api.post(
            f"{base_url}/api/register-push",
            json={"user_id": user_id, "platform": "ios", "device_token": "TEST_device_token"},
        )
        assert r.status_code in (200, 201), r.text


# ---------- WebSocket chat ----------
def _ws_url(http_base, token):
    base = http_base.replace("https://", "wss://").replace("http://", "ws://")
    return f"{base}/api/ws/chat?token={token}"


class TestWebsocket:
    def test_invalid_token_rejected(self, base_url):
        async def runner():
            url = _ws_url(base_url, "obviously.bad.token")
            try:
                async with websockets.connect(url, open_timeout=10) as ws:
                    try:
                        await asyncio.wait_for(ws.recv(), timeout=3)
                    except Exception:
                        pass
                    return getattr(ws, "close_code", None)
            except websockets.exceptions.InvalidStatus as e:
                return e.response.status_code
            except websockets.exceptions.ConnectionClosed as e:
                return e.code
            except Exception as e:  # noqa: BLE001
                return str(e)

        result = asyncio.run(runner())
        assert result in (4401, 401, 403), f"expected rejection, got {result!r}"

    def test_valid_token_connect_send_broadcast(self, base_url, gf_student_token):
        async def runner():
            url = _ws_url(base_url, gf_student_token)
            async with websockets.connect(url, open_timeout=10) as ws:
                marker = "TEST_WS_BROADCAST_HELLO"
                await ws.send(json.dumps({"text": marker}))
                raw = await asyncio.wait_for(ws.recv(), timeout=8)
                return json.loads(raw)

        msg = asyncio.run(runner())
        assert msg.get("text") == "TEST_WS_BROADCAST_HELLO"
        assert msg.get("sender_role") == "student"
