"""
Shared fixtures.

Unit tests override `get_deployment_service` so no real cluster is needed.
Integration tests (marked `integration`) hit minikube directly.
"""
import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, create_autospec
from kubernetes import client
from kubernetes.client.exceptions import ApiException


# ── Mock builders ────────────────────────────────────────────────────────────

def make_mock_apps_v1():
    return create_autospec(client.AppsV1Api, instance=True)


def make_mock_core_v1():
    return create_autospec(client.CoreV1Api, instance=True)


def _api_exc(status: int) -> ApiException:
    e = ApiException(status=status)
    e.reason = {404: "Not Found", 409: "Conflict", 422: "Unprocessable Entity"}.get(status, "Error")
    return e


# ── App client with mocked K8s ───────────────────────────────────────────────

@pytest.fixture
def mock_clients():
    """Returns (apps_v1, core_v1) mocks with safe defaults."""
    apps = make_mock_apps_v1()
    core = make_mock_core_v1()

    # namespace already exists
    core.read_namespace.return_value = MagicMock()
    # deployment does not exist yet (for create)
    apps.read_namespaced_deployment.side_effect = _api_exc(404)
    # list returns empty
    apps.list_deployment_for_all_namespaces.return_value = MagicMock(items=[])
    apps.list_namespaced_deployment.return_value = MagicMock(items=[])

    return apps, core


@pytest.fixture
def api_client(mock_clients):
    """FastAPI TestClient with K8s mocked out."""
    from api.main import app
    from api.k8s.deployments import get_deployment_service
    from api.k8s.deployments import DeploymentService

    apps, core = mock_clients

    app.dependency_overrides[get_deployment_service] = lambda: DeploymentService(apps, core)
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c
    app.dependency_overrides.clear()


# ── Helpers ──────────────────────────────────────────────────────────────────

def make_k8s_deployment(name="test-app", namespace="default", uid="uid-1234",
                         image="nginx:latest", replicas=1):
    """Minimal V1Deployment object suitable for service unit tests."""
    dep = MagicMock(spec=client.V1Deployment)
    dep.metadata = MagicMock(
        name=name, namespace=namespace,
        uid=uid, creation_timestamp=None, labels={},
    )
    dep.spec = MagicMock()
    dep.spec.replicas = replicas
    dep.spec.selector = MagicMock(match_labels={"app": name})
    dep.spec.template = MagicMock()
    dep.spec.template.spec = MagicMock()
    container = MagicMock()
    container.name = name
    container.image = image
    dep.spec.template.spec.containers = [container]
    dep.status = MagicMock(
        ready_replicas=replicas,
        available_replicas=replicas,
        unavailable_replicas=0,
        conditions=[],
    )
    return dep
