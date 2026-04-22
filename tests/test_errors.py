"""
Error scenario tests — 404, 409, 500 responses.
All run without a real cluster.
"""
import pytest
from unittest.mock import MagicMock, patch
from kubernetes.client.exceptions import ApiException


VALID_PAYLOAD = {"name": "my-app", "image": "nginx:latest"}


def _api_exc(status: int, reason: str = "Error") -> ApiException:
    e = ApiException(status=status)
    e.reason = reason
    return e


# ── 409 Conflict ─────────────────────────────────────────────────────────────

def test_create_duplicate_returns_409(api_client, mock_clients):
    """Creating a deployment with a name that already exists → 409."""
    apps, _ = mock_clients
    # read_namespaced_deployment succeeds → deployment already exists
    apps.read_namespaced_deployment.side_effect = None
    apps.read_namespaced_deployment.return_value = MagicMock()

    r = api_client.post("/api/deployments", json=VALID_PAYLOAD)
    assert r.status_code == 409
    body = r.json()
    assert "already exists" in body["detail"]


# ── 404 Not Found ────────────────────────────────────────────────────────────

def test_get_nonexistent_returns_404(api_client, mock_clients):
    """GET by unknown UID → 404."""
    apps, _ = mock_clients
    apps.list_deployment_for_all_namespaces.return_value = MagicMock(items=[])

    r = api_client.get("/api/deployments/nonexistent-uid")
    assert r.status_code == 404


def test_patch_nonexistent_returns_404(api_client, mock_clients):
    apps, _ = mock_clients
    apps.list_deployment_for_all_namespaces.return_value = MagicMock(items=[])

    r = api_client.patch("/api/deployments/nonexistent-uid", json={"replicas": 2})
    assert r.status_code == 404


def test_delete_nonexistent_returns_404(api_client, mock_clients):
    apps, _ = mock_clients
    apps.list_deployment_for_all_namespaces.return_value = MagicMock(items=[])

    r = api_client.delete("/api/deployments/nonexistent-uid")
    assert r.status_code == 404


def test_restart_nonexistent_returns_404(api_client, mock_clients):
    apps, _ = mock_clients
    apps.list_deployment_for_all_namespaces.return_value = MagicMock(items=[])

    r = api_client.post("/api/deployments/nonexistent-uid/restart")
    assert r.status_code == 404


# ── 500 K8s API failure ───────────────────────────────────────────────────────

def test_k8s_api_failure_on_list_returns_500(api_client, mock_clients):
    apps, _ = mock_clients
    apps.list_deployment_for_all_namespaces.side_effect = _api_exc(503, "Service Unavailable")

    r = api_client.get("/api/deployments")
    assert r.status_code == 500
    assert "K8s API error" in r.json()["detail"]


def test_k8s_api_failure_on_create_returns_500(api_client, mock_clients):
    apps, _ = mock_clients
    apps.read_namespaced_deployment.side_effect = ApiException(status=404)
    apps.create_namespaced_deployment.side_effect = _api_exc(500, "Internal Server Error")

    r = api_client.post("/api/deployments", json=VALID_PAYLOAD)
    assert r.status_code == 500
    assert "K8s API error" in r.json()["detail"]


# ── Structured error body ────────────────────────────────────────────────────

def test_error_response_has_detail_field(api_client, mock_clients):
    """All error responses must include a 'detail' key."""
    apps, _ = mock_clients
    apps.list_deployment_for_all_namespaces.return_value = MagicMock(items=[])

    r = api_client.get("/api/deployments/missing-uid")
    assert r.status_code == 404
    body = r.json()
    assert "detail" in body
