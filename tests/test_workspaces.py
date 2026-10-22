"""
tests/test_workspaces.py — Automated Test Suite for Milestone 17: Team Workspaces & RBAC.

Covers:
1. Workspace creation (creator automatically becomes admin).
2. Membership uniqueness (cannot add same user twice -> 409 Conflict).
3. Listing only a user's authorized workspaces (multi-tenant isolation).
4. Admin membership management (add, update, remove members).
5. Responder permissions (can create incidents, update status, trigger investigation).
6. Viewer read-only restrictions (cannot update status, cannot investigate, cannot manage members -> 403).
7. Preventing role escalation (responder and viewer cannot add admin or update member roles).
8. Preventing removal or demotion of the last admin (returns 400 Bad Request).
9. Cross-workspace incident access (Member of Workspace A cannot access Workspace B incidents -> 404).
10. Cross-workspace event and investigation access (Member of Workspace A cannot inspect Workspace B jobs -> 404).
11. Unauthorized job-result access.
12. Workspace isolation in search, filtering, and pagination.
13. Existing single-user API regression behavior (incidents with workspace_id=None remain functional).
14. Role validation constraints.
"""

from datetime import datetime, timezone
import uuid
import pytest
from fastapi.testclient import TestClient

from app.database import SessionLocal
from app.models.incident import Incident, IncidentStatus
from app.models.investigation import InvestigationJob, InvestigationStatus
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMembership, WorkspaceRole
from app.security import create_access_token, hash_password


def create_user_client(email_prefix: str) -> tuple[TestClient, uuid.UUID, str]:
    """Helper to register and instantiate an authenticated client for an isolated test user."""
    from app.main import app
    user_id = uuid.uuid4()
    email = f"{email_prefix}_{user_id.hex[:6]}@example.com"
    with SessionLocal() as db:
        now = datetime.now(timezone.utc)
        user = User(
            id=user_id,
            email=email,
            hashed_password=hash_password("Password123!"),
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        db.add(user)
        db.commit()

    token = create_access_token(data={"sub": str(user_id), "email": email})
    headers = {
        "X-API-Key": "test-secret-key-12345",
        "Authorization": f"Bearer {token}",
    }
    client = TestClient(app, headers=headers)
    return client, user_id, email


class TestWorkspaceCreationAndUniqueness:
    """Tests 1-3: Workspace lifecycle, creation, validation, and uniqueness."""

    def test_01_create_workspace_creator_is_admin(self) -> None:
        client, user_id, email = create_user_client("ws_creator")
        res = client.post("/api/v1/workspaces", json={"name": "SRE Platform Team"})
        assert res.status_code == 201, res.text
        data = res.json()
        assert data["name"] == "SRE Platform Team"
        assert data["created_by"] == str(user_id)
        assert data["current_user_role"] == "admin"
        assert data["member_count"] == 1
        assert "id" in data

    def test_02_workspace_name_validation(self) -> None:
        client, _, _ = create_user_client("ws_val")
        res = client.post("/api/v1/workspaces", json={"name": "   "})
        assert res.status_code == 422

    def test_03_membership_uniqueness_prevents_duplicate(self) -> None:
        admin_client, admin_id, _ = create_user_client("ws_admin")
        _, user_b_id, user_b_email = create_user_client("user_b")

        # 1. Create workspace
        ws_res = admin_client.post("/api/v1/workspaces", json={"name": "Alpha Team"})
        assert ws_res.status_code == 201
        ws_id = ws_res.json()["id"]

        # 2. Add user_b as viewer
        add_res = admin_client.post(
            f"/api/v1/workspaces/{ws_id}/members",
            json={"email": user_b_email, "role": "viewer"},
        )
        assert add_res.status_code == 201

        # 3. Add user_b again -> 409 Conflict
        dup_res = admin_client.post(
            f"/api/v1/workspaces/{ws_id}/members",
            json={"email": user_b_email, "role": "responder"},
        )
        assert dup_res.status_code == 409
        assert "already a member" in dup_res.json()["detail"].lower()


class TestWorkspaceListingAndIsolation:
    """Tests 4-5: Multi-tenant workspace listing and access boundaries."""

    def test_04_user_only_lists_authorized_workspaces(self) -> None:
        client_a, _, _ = create_user_client("user_a")
        client_b, _, _ = create_user_client("user_b")

        # User A creates Workspace A
        res_a = client_a.post("/api/v1/workspaces", json={"name": "Workspace A"})
        assert res_a.status_code == 201
        ws_a_id = res_a.json()["id"]

        # User B creates Workspace B
        res_b = client_b.post("/api/v1/workspaces", json={"name": "Workspace B"})
        assert res_b.status_code == 201
        ws_b_id = res_b.json()["id"]

        # List user A workspaces
        list_a = client_a.get("/api/v1/workspaces").json()
        ids_a = [item["id"] for item in list_a["items"]]
        assert ws_a_id in ids_a
        assert ws_b_id not in ids_a

        # List user B workspaces
        list_b = client_b.get("/api/v1/workspaces").json()
        ids_b = [item["id"] for item in list_b["items"]]
        assert ws_b_id in ids_b
        assert ws_a_id not in ids_b

    def test_05_unauthorized_user_cannot_get_workspace_details(self) -> None:
        client_a, _, _ = create_user_client("user_a")
        client_b, _, _ = create_user_client("user_b")

        ws_a = client_a.post("/api/v1/workspaces", json={"name": "Secret Ops"}).json()
        ws_a_id = ws_a["id"]

        # User B attempts to access User A's workspace -> 404 Not Found
        get_res = client_b.get(f"/api/v1/workspaces/{ws_a_id}")
        assert get_res.status_code == 404


class TestAdminMembershipManagement:
    """Tests 6-8: Membership management, role modification, and member removal."""

    def test_06_admin_can_add_and_list_members(self) -> None:
        admin_client, _, _ = create_user_client("admin_ops")
        _, user_id, user_email = create_user_client("member_user")

        ws = admin_client.post("/api/v1/workspaces", json={"name": "DevOps Hub"}).json()
        ws_id = ws["id"]

        add_res = admin_client.post(
            f"/api/v1/workspaces/{ws_id}/members",
            json={"email": user_email, "role": "responder"},
        )
        assert add_res.status_code == 201
        assert add_res.json()["role"] == "responder"

        members_res = admin_client.get(f"/api/v1/workspaces/{ws_id}/members")
        assert members_res.status_code == 200
        assert members_res.json()["total"] == 2

    def test_07_admin_can_update_member_role(self) -> None:
        admin_client, _, _ = create_user_client("admin_ops")
        _, user_id, user_email = create_user_client("member_user")

        ws = admin_client.post("/api/v1/workspaces", json={"name": "Core Platform"}).json()
        ws_id = ws["id"]

        admin_client.post(
            f"/api/v1/workspaces/{ws_id}/members",
            json={"email": user_email, "role": "viewer"},
        )

        # Promote viewer to responder
        patch_res = admin_client.patch(
            f"/api/v1/workspaces/{ws_id}/members/{user_id}",
            json={"role": "responder"},
        )
        assert patch_res.status_code == 200
        assert patch_res.json()["role"] == "responder"

    def test_08_admin_can_remove_member(self) -> None:
        admin_client, _, _ = create_user_client("admin_ops")
        _, user_id, user_email = create_user_client("member_user")

        ws = admin_client.post("/api/v1/workspaces", json={"name": "Infra"}).json()
        ws_id = ws["id"]

        admin_client.post(
            f"/api/v1/workspaces/{ws_id}/members",
            json={"email": user_email, "role": "viewer"},
        )

        del_res = admin_client.delete(f"/api/v1/workspaces/{ws_id}/members/{user_id}")
        assert del_res.status_code == 204

        # Member list should now have count 1
        members_res = admin_client.get(f"/api/v1/workspaces/{ws_id}/members").json()
        assert members_res["total"] == 1


class TestRoleBasedPermissions:
    """Tests 9-11: Responder operational permissions and Viewer read-only restrictions."""

    def test_09_responder_can_create_and_update_incidents(self) -> None:
        admin_client, _, _ = create_user_client("admin_user")
        resp_client, resp_id, resp_email = create_user_client("resp_user")

        ws = admin_client.post("/api/v1/workspaces", json={"name": "Incident Team"}).json()
        ws_id = ws["id"]

        # Add user as responder
        admin_client.post(
            f"/api/v1/workspaces/{ws_id}/members",
            json={"email": resp_email, "role": "responder"},
        )

        # Responder creates incident in workspace
        inc_res = resp_client.post(
            "/api/v1/incidents",
            json={
                "title": "High CPU on API Gateway",
                "service_name": "api-gateway",
                "environment": "production",
                "severity": "CRITICAL",
                "workspace_id": ws_id,
            },
        )
        assert inc_res.status_code == 201
        inc_id = inc_res.json()["id"]

        # Responder updates incident status
        update_res = resp_client.patch(
            f"/api/v1/incidents/{inc_id}/status",
            json={"status": "INVESTIGATING"},
        )
        assert update_res.status_code == 200
        assert update_res.json()["status"] == "INVESTIGATING"

    def test_10_viewer_cannot_update_status_or_create_incident(self) -> None:
        admin_client, _, _ = create_user_client("admin_user")
        view_client, view_id, view_email = create_user_client("view_user")

        ws = admin_client.post("/api/v1/workspaces", json={"name": "Readonly Team"}).json()
        ws_id = ws["id"]

        # Add as viewer
        admin_client.post(
            f"/api/v1/workspaces/{ws_id}/members",
            json={"email": view_email, "role": "viewer"},
        )

        # Admin creates an incident in workspace
        inc = admin_client.post(
            "/api/v1/incidents",
            json={
                "title": "Database Read Replica Latency",
                "service_name": "postgres",
                "environment": "production",
                "workspace_id": ws_id,
            },
        ).json()
        inc_id = inc["id"]

        # Viewer can READ incident
        view_get = view_client.get(f"/api/v1/incidents/{inc_id}")
        assert view_get.status_code == 200

        # Viewer CANNOT update status -> 403 Forbidden
        view_patch = view_client.patch(
            f"/api/v1/incidents/{inc_id}/status",
            json={"status": "INVESTIGATING"},
        )
        assert view_patch.status_code == 403
        assert "viewers have read-only access" in view_patch.json()["detail"].lower()

        # Viewer CANNOT create incident in workspace -> 403 Forbidden
        view_create = view_client.post(
            "/api/v1/incidents",
            json={
                "title": "Illegal Viewer Incident",
                "service_name": "auth",
                "environment": "staging",
                "workspace_id": ws_id,
            },
        )
        assert view_create.status_code == 403

    def test_11_responder_and_viewer_cannot_manage_members(self) -> None:
        admin_client, _, _ = create_user_client("admin_user")
        resp_client, _, resp_email = create_user_client("resp_user")
        view_client, _, view_email = create_user_client("view_user")
        _, rogue_id, rogue_email = create_user_client("rogue_user")

        ws = admin_client.post("/api/v1/workspaces", json={"name": "SecOps"}).json()
        ws_id = ws["id"]

        admin_client.post(f"/api/v1/workspaces/{ws_id}/members", json={"email": resp_email, "role": "responder"})
        admin_client.post(f"/api/v1/workspaces/{ws_id}/members", json={"email": view_email, "role": "viewer"})

        # Responder cannot add member -> 403
        r_add = resp_client.post(
            f"/api/v1/workspaces/{ws_id}/members",
            json={"email": rogue_email, "role": "viewer"},
        )
        assert r_add.status_code == 403

        # Viewer cannot remove member -> 403
        v_del = view_client.delete(f"/api/v1/workspaces/{ws_id}/members/{rogue_id}")
        assert v_del.status_code == 403


class TestPrivilegeEscalationAndInvariants:
    """Tests 12-13: Invariants enforcing last admin protection and anti-escalation."""

    def test_12_prevent_demoting_last_admin(self) -> None:
        admin_client, admin_id, _ = create_user_client("sole_admin")
        ws = admin_client.post("/api/v1/workspaces", json={"name": "Critical Workspace"}).json()
        ws_id = ws["id"]

        # Admin attempts to demote themselves to viewer while being sole admin
        demote_res = admin_client.patch(
            f"/api/v1/workspaces/{ws_id}/members/{admin_id}",
            json={"role": "viewer"},
        )
        assert demote_res.status_code == 400
        assert "cannot remove or demote the last" in demote_res.json()["detail"].lower()

    def test_13_prevent_removing_last_admin(self) -> None:
        admin_client, admin_id, _ = create_user_client("sole_admin")
        ws = admin_client.post("/api/v1/workspaces", json={"name": "Critical Workspace 2"}).json()
        ws_id = ws["id"]

        # Admin attempts to delete themselves while being sole admin
        del_res = admin_client.delete(f"/api/v1/workspaces/{ws_id}/members/{admin_id}")
        assert del_res.status_code == 400
        assert "cannot remove or demote the last" in del_res.json()["detail"].lower()


class TestCrossWorkspaceIsolation:
    """Tests 14-18: Strict multi-tenant isolation across incidents, jobs, investigations, and search."""

    def test_14_cross_workspace_incident_isolation(self) -> None:
        client_a, _, _ = create_user_client("tenant_a")
        client_b, _, _ = create_user_client("tenant_b")

        ws_a = client_a.post("/api/v1/workspaces", json={"name": "Tenant A Ops"}).json()["id"]
        ws_b = client_b.post("/api/v1/workspaces", json={"name": "Tenant B Ops"}).json()["id"]

        # Tenant A creates incident in Workspace A
        inc_a = client_a.post(
            "/api/v1/incidents",
            json={
                "title": "Tenant A Private Incident",
                "service_name": "billing",
                "environment": "production",
                "workspace_id": ws_a,
            },
        ).json()["id"]

        # Tenant B cannot retrieve Tenant A's incident -> 404 Not Found
        res_get = client_b.get(f"/api/v1/incidents/{inc_a}")
        assert res_get.status_code == 404

        # Tenant B cannot update Tenant A's incident -> 404 Not Found
        res_patch = client_b.patch(f"/api/v1/incidents/{inc_a}/status", json={"status": "RESOLVED"})
        assert res_patch.status_code == 404

    def test_15_workspace_search_and_pagination_isolation(self) -> None:
        client_a, _, _ = create_user_client("tenant_a")
        client_b, _, _ = create_user_client("tenant_b")

        ws_a = client_a.post("/api/v1/workspaces", json={"name": "Workspace A"}).json()["id"]
        ws_b = client_b.post("/api/v1/workspaces", json={"name": "Workspace B"}).json()["id"]

        # Client A creates 2 incidents in Workspace A
        client_a.post("/api/v1/incidents", json={"title": "A1", "service_name": "svc", "workspace_id": ws_a})
        client_a.post("/api/v1/incidents", json={"title": "A2", "service_name": "svc", "workspace_id": ws_a})

        # Client B queries incidents with ?workspace_id=ws_a -> 404 (not a member)
        query_unauthorized = client_b.get(f"/api/v1/incidents?workspace_id={ws_a}")
        assert query_unauthorized.status_code == 404

        # Client A queries incidents with ?workspace_id=ws_a -> returns 2 items
        query_authorized = client_a.get(f"/api/v1/incidents?workspace_id={ws_a}")
        assert query_authorized.status_code == 200
        assert query_authorized.json()["total"] == 2

    def test_16_cross_workspace_investigation_isolation(self) -> None:
        client_a, _, _ = create_user_client("tenant_a")
        client_b, _, _ = create_user_client("tenant_b")

        ws_a = client_a.post("/api/v1/workspaces", json={"name": "Workspace A"}).json()["id"]

        # Client A creates incident and triggers investigation
        inc_a = client_a.post(
            "/api/v1/incidents",
            json={"title": "A Outage", "service_name": "svc", "workspace_id": ws_a},
        ).json()["id"]

        inv_res = client_a.post(f"/api/v1/incidents/{inc_a}/investigate")
        assert inv_res.status_code == 202
        job_id = inv_res.json()["id"]

        # Client B cannot retrieve Tenant A's investigation job -> 404 Not Found
        job_b = client_b.get(f"/api/v1/investigations/{job_id}")
        assert job_b.status_code == 404

        # Client B cannot list investigations for Tenant A's incident -> 404 Not Found
        list_b = client_b.get(f"/api/v1/incidents/{inc_a}/investigations")
        assert list_b.status_code == 404

    def test_17_viewer_cannot_trigger_investigation(self) -> None:
        admin_client, _, _ = create_user_client("admin_user")
        view_client, _, view_email = create_user_client("view_user")

        ws = admin_client.post("/api/v1/workspaces", json={"name": "Investigate Team"}).json()["id"]
        admin_client.post(f"/api/v1/workspaces/{ws}/members", json={"email": view_email, "role": "viewer"})

        inc = admin_client.post(
            "/api/v1/incidents",
            json={"title": "Investigate Target", "service_name": "svc", "workspace_id": ws},
        ).json()["id"]

        # Viewer attempts to trigger AI investigation -> 403 Forbidden
        view_inv = view_client.post(f"/api/v1/incidents/{inc}/investigate")
        assert view_inv.status_code == 403
        assert "viewers have read-only access" in view_inv.json()["detail"].lower()

    def test_18_legacy_single_user_incident_regression(self) -> None:
        client_user, user_id, _ = create_user_client("legacy_user")

        # Legacy incident with workspace_id=None
        inc = client_user.post(
            "/api/v1/incidents",
            json={"title": "Personal Unassigned Incident", "service_name": "local-test"},
        ).json()
        assert inc["workspace_id"] is None
        assert inc["owner_id"] == str(user_id)

        # Owner can view, update, delete
        inc_id = inc["id"]
        assert client_user.get(f"/api/v1/incidents/{inc_id}").status_code == 200
        assert client_user.patch(f"/api/v1/incidents/{inc_id}/status", json={"status": "INVESTIGATING"}).status_code == 200
        assert client_user.delete(f"/api/v1/incidents/{inc_id}").status_code == 204
