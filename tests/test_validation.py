"""
Input validation tests — all run without a real K8s cluster.
FastAPI returns 422 for Pydantic validation failures.
"""
import pytest
from unittest.mock import MagicMock
from kubernetes.client.exceptions import ApiException


VALID = {"name": "my-app", "image": "nginx:latest"}


# ── Name validation ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("bad_name", [
    "MyApp",           # uppercase
    "my_app",          # underscore
    "-myapp",          # leading hyphen
    "myapp-",          # trailing hyphen
    "a" * 64,          # too long
    "",                # empty
    "my app",          # space
])
def test_invalid_name_rejected(api_client, bad_name):
    r = api_client.post("/api/deployments", json={**VALID, "name": bad_name})
    assert r.status_code == 422, f"Expected 422 for name={bad_name!r}, got {r.status_code}"


@pytest.mark.parametrize("good_name", [
    "myapp",
    "my-app",
    "a",
    "app123",
    "a" * 63,
    "x1-y2-z3",
])
def test_valid_name_accepted(api_client, mock_clients, good_name):
    apps, core = mock_clients
    # make create succeed
    created = MagicMock()
    created.metadata = MagicMock(name=good_name, namespace="default", uid="u1",
                                  creation_timestamp=None)
    created.spec = MagicMock(replicas=1)
    created.spec.template.spec.containers = [MagicMock(image="nginx:latest")]
    created.status = MagicMock(ready_replicas=0, available_replicas=0,
                                unavailable_replicas=1, conditions=[])
    apps.create_namespaced_deployment.return_value = created

    r = api_client.post("/api/deployments", json={**VALID, "name": good_name})
    assert r.status_code == 201, f"Expected 201 for name={good_name!r}, got {r.status_code}: {r.text}"


# ── Replica validation ───────────────────────────────────────────────────────

def test_negative_replicas_rejected(api_client):
    r = api_client.post("/api/deployments", json={**VALID, "replicas": -1})
    assert r.status_code == 422


def test_zero_replicas_accepted(api_client, mock_clients):
    apps, _ = mock_clients
    dep = MagicMock()
    dep.metadata = MagicMock(name="my-app", namespace="default", uid="u1",
                               creation_timestamp=None)
    dep.spec = MagicMock(replicas=0)
    dep.spec.template.spec.containers = [MagicMock(image="nginx:latest")]
    dep.status = MagicMock(ready_replicas=0, available_replicas=0,
                            unavailable_replicas=0, conditions=[])
    apps.create_namespaced_deployment.return_value = dep
    r = api_client.post("/api/deployments", json={**VALID, "replicas": 0})
    assert r.status_code == 201


# ── Image validation ─────────────────────────────────────────────────────────

def test_empty_image_rejected(api_client):
    r = api_client.post("/api/deployments", json={"name": "my-app", "image": ""})
    assert r.status_code == 422


def test_image_with_space_rejected(api_client):
    r = api_client.post("/api/deployments", json={**VALID, "image": "nginx: latest"})
    assert r.status_code == 422


# ── Missing required fields ──────────────────────────────────────────────────

def test_missing_name(api_client):
    r = api_client.post("/api/deployments", json={"image": "nginx:latest"})
    assert r.status_code == 422


def test_missing_image(api_client):
    r = api_client.post("/api/deployments", json={"name": "my-app"})
    assert r.status_code == 422


# ── Resource format validation ───────────────────────────────────────────────

@pytest.mark.parametrize("cpu", ["invalid-cpu", "100x", "abc"])
def test_invalid_cpu_format(api_client, cpu):
    r = api_client.post("/api/deployments", json={
        **VALID,
        "resources": {"requests": {"cpu": cpu}}
    })
    assert r.status_code == 422, f"Expected 422 for cpu={cpu!r}"


@pytest.mark.parametrize("mem", ["invalid", "100xx", "gibberish"])
def test_invalid_memory_format(api_client, mem):
    r = api_client.post("/api/deployments", json={
        **VALID,
        "resources": {"requests": {"memory": mem}}
    })
    assert r.status_code == 422


# ── Port validation ──────────────────────────────────────────────────────────

def test_invalid_port_zero(api_client):
    r = api_client.post("/api/deployments", json={**VALID, "port": 0})
    assert r.status_code == 422


def test_invalid_port_too_high(api_client):
    r = api_client.post("/api/deployments", json={**VALID, "port": 99999})
    assert r.status_code == 422


# ── PATCH validation ─────────────────────────────────────────────────────────

def test_patch_requires_at_least_one_field(api_client):
    r = api_client.patch("/api/deployments/some-uid", json={})
    assert r.status_code == 422


def test_patch_negative_replicas(api_client):
    r = api_client.patch("/api/deployments/some-uid", json={"replicas": -5})
    assert r.status_code == 422
