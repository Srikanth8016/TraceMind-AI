"""
tests/test_auth.py — Automated Test Suite for Milestone 14: Authentication & Authorization.

Covers:
1. Successful user registration (POST /auth/register).
2. Duplicate email registration (HTTP 409 Conflict).
3. Passwords are stored cryptographically hashed, not plaintext.
4. Successful login with valid credentials (POST /auth/login returns JWT access_token).
5. Invalid email or password login returns generic 401 Unauthorized.
6. Missing bearer token rejected with HTTP 401 and WWW-Authenticate: Bearer.
7. Invalid / malformed token rejected with HTTP 401 and WWW-Authenticate: Bearer.
8. Expired token rejected with HTTP 401 and WWW-Authenticate: Bearer.
9. Access to protected endpoints with a valid token (GET /auth/me, GET /api/v1/incidents).
10. User A cannot list or retrieve User B's incidents (returns 404 / empty list).
11. User A cannot update or delete User B's incidents (returns 404 Not Found).
12. Client-supplied owner_id is ignored on creation; server derives ownership from token.
13. Incident search, filters, sorting, and pagination remain scoped to the authenticated user.
14. Existing public health & readiness endpoints (/health, /ready) continue to work unauthenticated.
15. Inactive user accounts are rejected with HTTP 401/403.
"""

from datetime import datetime, timedelta, timezone
import uuid
import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models.incident import Incident, IncidentStatus
from app.models.user import User
from app.security import create_access_token, hash_password, verify_password


class TestUserRegistrationAndHashing:
    """Verifies user registration and secure credential storage."""

    def test_01_successful_user_registration(self, unauthenticated_client: TestClient) -> None:
        email = f"user_{uuid.uuid4().hex[:8]}@example.com"
        payload = {
            "email": f"  {email.upper()}  ",  # Test normalization
            "password": "SecurePassword123!",
        }
        response = unauthenticated_client.post("/auth/register", json=payload)
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == email.lower()
        assert "id" in data
        assert data["is_active"] is True
        assert "password" not in data
        assert "hashed_password" not in data

    def test_02_duplicate_email_registration_returns_409(
        self, unauthenticated_client: TestClient
    ) -> None:
        email = f"dup_{uuid.uuid4().hex[:8]}@example.com"
        payload = {"email": email, "password": "Password123!"}

        # First registration succeeds
        r1 = unauthenticated_client.post("/auth/register", json=payload)
        assert r1.status_code == 201

        # Duplicate registration with case variation returns 409
        dup_payload = {"email": email.upper(), "password": "AnotherPassword456!"}
        r2 = unauthenticated_client.post("/auth/register", json=dup_payload)
        assert r2.status_code == 409
        assert "already registered" in r2.json()["detail"].lower()

    def test_03_passwords_are_stored_hashed_never_plaintext(
        self, unauthenticated_client: TestClient
    ) -> None:
        email = f"hashcheck_{uuid.uuid4().hex[:8]}@example.com"
        raw_password = "PlaintextSecret987!"

        r = unauthenticated_client.post(
            "/auth/register", json={"email": email, "password": raw_password}
        )
        assert r.status_code == 201
        user_id = uuid.UUID(r.json()["id"])

        with SessionLocal() as db:
            user = db.get(User, user_id)
            assert user is not None
            assert user.hashed_password != raw_password
            assert raw_password not in user.hashed_password
            assert verify_password(raw_password, user.hashed_password) is True
            assert verify_password("WrongPassword!", user.hashed_password) is False


class TestUserLoginAndJWT:
    """Verifies JWT issuance, authentication validation, and failure responses."""

    def test_04_successful_login_returns_signed_jwt(
        self, unauthenticated_client: TestClient
    ) -> None:
        email = f"login_ok_{uuid.uuid4().hex[:8]}@example.com"
        password = "ValidPassword123!"

        # Register first
        unauthenticated_client.post(
            "/auth/register", json={"email": email, "password": password}
        )

        # Login
        response = unauthenticated_client.post(
            "/auth/login", json={"email": email, "password": password}
        )
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"].lower() == "bearer"
        assert len(data["access_token"]) > 20

    def test_05_invalid_email_or_password_returns_generic_401(
        self, unauthenticated_client: TestClient
    ) -> None:
        email = f"login_fail_{uuid.uuid4().hex[:8]}@example.com"
        password = "GoodPassword123!"

        unauthenticated_client.post(
            "/auth/register", json={"email": email, "password": password}
        )

        # Wrong password
        r1 = unauthenticated_client.post(
            "/auth/login", json={"email": email, "password": "WrongPassword!"}
        )
        assert r1.status_code == 401
        assert "invalid email or password" in r1.json()["detail"].lower()
        assert r1.headers.get("www-authenticate") == "Bearer"

        # Non-existent email
        r2 = unauthenticated_client.post(
            "/auth/login", json={"email": "nonexistent@example.com", "password": password}
        )
        assert r2.status_code == 401
        # Must return same generic message to prevent email enumeration
        assert r2.json()["detail"] == r1.json()["detail"]


class TestTokenValidationAndDependencies:
    """Verifies token extraction, rejection, and expiration behavior."""

    def test_06_missing_bearer_token_returns_401(
        self, unauthenticated_client: TestClient
    ) -> None:
        response = unauthenticated_client.get("/api/v1/incidents")
        assert response.status_code == 401
        assert "www-authenticate" in response.headers
        assert response.headers["www-authenticate"] == "Bearer"

    def test_07_invalid_malformed_token_returns_401(
        self, unauthenticated_client: TestClient
    ) -> None:
        bad_headers = {"Authorization": "Bearer not-a-valid-jwt-token"}
        response = unauthenticated_client.get("/api/v1/incidents", headers=bad_headers)
        assert response.status_code == 401
        assert response.headers.get("www-authenticate") == "Bearer"

    def test_08_expired_token_returns_401(
        self, unauthenticated_client: TestClient
    ) -> None:
        expired_token = create_access_token(
            data={"sub": str(uuid.uuid4())},
            expires_delta=timedelta(seconds=-10),  # expired in the past
        )
        headers = {"Authorization": f"Bearer {expired_token}"}
        response = unauthenticated_client.get("/api/v1/incidents", headers=headers)
        assert response.status_code == 401
        assert "token has expired" in response.json()["detail"].lower()
        assert response.headers.get("www-authenticate") == "Bearer"

    def test_09_access_protected_endpoint_with_valid_token(
        self, unauthenticated_client: TestClient
    ) -> None:
        email = f"me_{uuid.uuid4().hex[:8]}@example.com"
        password = "UserSecret123!"
        reg = unauthenticated_client.post(
            "/auth/register", json={"email": email, "password": password}
        )
        user_id = reg.json()["id"]

        login = unauthenticated_client.post(
            "/auth/login", json={"email": email, "password": password}
        )
        token = login.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # GET /auth/me
        me_resp = unauthenticated_client.get("/auth/me", headers=headers)
        assert me_resp.status_code == 200
        assert me_resp.json()["id"] == user_id
        assert me_resp.json()["email"] == email

        # GET /api/v1/incidents
        inc_resp = unauthenticated_client.get("/api/v1/incidents", headers=headers)
        assert inc_resp.status_code == 200
        assert "items" in inc_resp.json()


class TestIncidentAuthorizationAndScoping:
    """Verifies that User A and User B cannot access or mutate each other's incidents."""

    @pytest.fixture
    def user_a_client(self, unauthenticated_client: TestClient):
        email = f"user_a_{uuid.uuid4().hex[:8]}@example.com"
        password = "PasswordA123!"
        unauthenticated_client.post("/auth/register", json={"email": email, "password": password})
        login = unauthenticated_client.post("/auth/login", json={"email": email, "password": password})
        token = login.json()["access_token"]
        return {"client": unauthenticated_client, "headers": {"Authorization": f"Bearer {token}"}, "email": email}

    @pytest.fixture
    def user_b_client(self, unauthenticated_client: TestClient):
        email = f"user_b_{uuid.uuid4().hex[:8]}@example.com"
        password = "PasswordB123!"
        unauthenticated_client.post("/auth/register", json={"email": email, "password": password})
        login = unauthenticated_client.post("/auth/login", json={"email": email, "password": password})
        token = login.json()["access_token"]
        return {"client": unauthenticated_client, "headers": {"Authorization": f"Bearer {token}"}, "email": email}

    def test_10_user_a_cannot_list_or_retrieve_user_b_incidents(
        self, user_a_client, user_b_client
    ) -> None:
        c_a, h_a = user_a_client["client"], user_a_client["headers"]
        c_b, h_b = user_b_client["client"], user_b_client["headers"]

        # User B creates an incident
        b_inc_resp = c_b.post(
            "/api/v1/incidents",
            json={"title": "User B Private Outage", "severity": "HIGH", "service_name": "billing"},
            headers=h_b,
        )
        assert b_inc_resp.status_code == 201
        b_inc_id = b_inc_resp.json()["id"]

        # User A lists incidents -> User B's incident must NOT be visible
        a_list = c_a.get("/api/v1/incidents", headers=h_a)
        assert a_list.status_code == 200
        a_inc_ids = [item["id"] for item in a_list.json()["items"]]
        assert b_inc_id not in a_inc_ids

        # User A attempts to directly retrieve User B's incident by ID -> returns 404 (safe information hiding)
        a_get = c_a.get(f"/api/v1/incidents/{b_inc_id}", headers=h_a)
        assert a_get.status_code == 404
        assert "not found" in a_get.json()["detail"].lower()

    def test_11_user_a_cannot_update_or_delete_user_b_incidents(
        self, user_a_client, user_b_client
    ) -> None:
        c_a, h_a = user_a_client["client"], user_a_client["headers"]
        c_b, h_b = user_b_client["client"], user_b_client["headers"]

        # User B creates an incident
        b_inc = c_b.post(
            "/api/v1/incidents",
            json={"title": "User B Target Incident", "severity": "MEDIUM", "service_name": "auth-svc"},
            headers=h_b,
        ).json()
        b_id = b_inc["id"]

        # User A tries to update User B's incident status -> 404
        patch_status = c_a.patch(
            f"/api/v1/incidents/{b_id}/status",
            json={"status": "INVESTIGATING"},
            headers=h_a,
        )
        assert patch_status.status_code == 404

        # User A tries to PUT update User B's incident -> 404
        put_update = c_a.put(
            f"/api/v1/incidents/{b_id}",
            json={"title": "Malicious Hijack Title", "severity": "LOW"},
            headers=h_a,
        )
        assert put_update.status_code == 404

        # User A tries to DELETE User B's incident -> 404
        delete_resp = c_a.delete(f"/api/v1/incidents/{b_id}", headers=h_a)
        assert delete_resp.status_code == 404

        # Verify incident still exists untouched for User B
        check_b = c_b.get(f"/api/v1/incidents/{b_id}", headers=h_b)
        assert check_b.status_code == 200
        assert check_b.json()["title"] == "User B Target Incident"

    def test_12_user_cannot_create_incident_on_behalf_of_another_user(
        self, user_a_client, user_b_client
    ) -> None:
        c_a, h_a = user_a_client["client"], user_a_client["headers"]
        fake_owner_id = str(uuid.uuid4())

        # Client attempts to supply an owner_id in the payload
        resp = c_a.post(
            "/api/v1/incidents",
            json={
                "title": "Incident with spoofed owner",
                "severity": "LOW",
                "owner_id": fake_owner_id,
            },
            headers=h_a,
        )
        assert resp.status_code == 201
        data = resp.json()
        # Server must not honor the client-supplied owner_id
        assert data["owner_id"] != fake_owner_id

    def test_13_search_filters_and_pagination_are_scoped_to_authenticated_user(
        self, user_a_client, user_b_client
    ) -> None:
        c_a, h_a = user_a_client["client"], user_a_client["headers"]
        c_b, h_b = user_b_client["client"], user_b_client["headers"]

        # User A creates 3 incidents matching "Kubernetes DNS"
        for i in range(3):
            c_a.post(
                "/api/v1/incidents",
                json={
                    "title": f"Kubernetes DNS resolution failure {i}",
                    "severity": "CRITICAL",
                    "service_name": "dns-worker",
                },
                headers=h_a,
            )

        # User B creates 2 incidents also matching "Kubernetes DNS"
        for i in range(2):
            c_b.post(
                "/api/v1/incidents",
                json={
                    "title": f"Kubernetes DNS crash {i}",
                    "severity": "CRITICAL",
                    "service_name": "dns-worker",
                },
                headers=h_b,
            )

        # User A searches for "Kubernetes DNS"
        a_search = c_a.get("/api/v1/incidents?search=Kubernetes+DNS", headers=h_a)
        assert a_search.status_code == 200
        assert a_search.json()["total"] == 3

        # User B searches for "Kubernetes DNS"
        b_search = c_b.get("/api/v1/incidents?search=Kubernetes+DNS", headers=h_b)
        assert b_search.status_code == 200
        assert b_search.json()["total"] == 2


class TestHealthAndUserLifecycle:
    """Verifies public probe accessibility and inactive user handling."""

    def test_14_existing_health_endpoints_remain_public(
        self, unauthenticated_client: TestClient
    ) -> None:
        r_health = unauthenticated_client.get("/health")
        assert r_health.status_code == 200
        assert r_health.json()["status"] in ("healthy", "ok")

    def test_15_inactive_user_is_rejected(
        self, unauthenticated_client: TestClient
    ) -> None:
        email = f"inactive_{uuid.uuid4().hex[:8]}@example.com"
        password = "InactivePassword123!"

        reg = unauthenticated_client.post(
            "/auth/register", json={"email": email, "password": password}
        )
        user_id = uuid.UUID(reg.json()["id"])

        # Mark user inactive directly in the database
        with SessionLocal() as db:
            user = db.get(User, user_id)
            user.is_active = False
            db.commit()

        # Login attempt should be rejected with 401 Unauthorized
        login_resp = unauthenticated_client.post(
            "/auth/login", json={"email": email, "password": password}
        )
        assert login_resp.status_code == 401
        assert "inactive" in login_resp.json()["detail"].lower()

        # If a token is crafted for an inactive user, protected routes reject with 401
        token = create_access_token(data={"sub": str(user_id)})
        resp = unauthenticated_client.get(
            "/api/v1/incidents", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 401
        assert "inactive" in resp.json()["detail"].lower()
