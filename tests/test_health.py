"""
Unit tests for the health status computation logic.
No cluster or HTTP calls — pure logic tests on K8s object mocks.
"""
import pytest
from unittest.mock import MagicMock

from api.k8s.health import compute_health, HealthStatus


def _dep(desired=3, ready=3, available=3, unavailable=0, conditions=None):
    dep = MagicMock()
    dep.spec.replicas = desired
    dep.status.ready_replicas = ready
    dep.status.available_replicas = available
    dep.status.unavailable_replicas = unavailable
    dep.status.conditions = conditions or []
    return dep


def _pod_waiting(reason: str):
    pod = MagicMock()
    cs = MagicMock()
    cs.state.waiting.reason = reason
    cs.state.running = None
    cs.state.terminated = None
    pod.status.container_statuses = [cs]
    return pod


def _cond(type_, status, reason=None):
    c = MagicMock()
    c.type = type_
    c.status = status
    c.reason = reason
    return c


# ── Basic cases ──────────────────────────────────────────────────────────────

def test_all_ready_is_healthy():
    assert compute_health(_dep(3, 3, 3, 0)) == HealthStatus.HEALTHY


def test_scaled_to_zero_is_healthy():
    assert compute_health(_dep(0, 0, 0, 0)) == HealthStatus.HEALTHY


def test_none_ready_is_failing():
    assert compute_health(_dep(3, 0, 0, 3)) == HealthStatus.FAILING


def test_some_ready_is_degraded():
    assert compute_health(_dep(3, 1, 1, 2)) == HealthStatus.DEGRADED


def test_none_deployment_is_unknown():
    assert compute_health(None) == HealthStatus.UNKNOWN


def test_none_status_is_unknown():
    dep = MagicMock()
    dep.status = None
    assert compute_health(dep) == HealthStatus.UNKNOWN


# ── Pod-level failures ───────────────────────────────────────────────────────

@pytest.mark.parametrize("reason", [
    "CrashLoopBackOff",
    "ImagePullBackOff",
    "ErrImagePull",
    "InvalidImageName",
    "OOMKilled",
])
def test_crash_reason_is_failing(reason):
    dep = _dep(1, 0, 0, 1)
    pod = _pod_waiting(reason)
    assert compute_health(dep, [pod]) == HealthStatus.FAILING


def test_unknown_waiting_reason_uses_replica_count():
    dep = _dep(3, 1, 1, 2)
    pod = _pod_waiting("ContainerCreating")
    # ContainerCreating is normal; should fall through to replica-based DEGRADED
    assert compute_health(dep, [pod]) == HealthStatus.DEGRADED


# ── Progressing ──────────────────────────────────────────────────────────────

def test_rollout_in_progress():
    cond = _cond("Progressing", "True", "ReplicaSetUpdated")
    dep = _dep(3, 1, 1, 2, conditions=[cond])
    assert compute_health(dep, []) == HealthStatus.PROGRESSING


def test_new_replicaset_created_is_progressing():
    cond = _cond("Progressing", "True", "NewReplicaSetCreated")
    dep = _dep(3, 0, 0, 3, conditions=[cond])
    assert compute_health(dep, []) == HealthStatus.PROGRESSING


def test_progressing_condition_false_uses_replicas():
    cond = _cond("Progressing", "False", "ReplicaSetUpdated")
    dep = _dep(3, 2, 2, 1, conditions=[cond])
    # condition status=False means it finished/failed; fall through to replica check
    assert compute_health(dep, []) == HealthStatus.DEGRADED


# ── Pods with no status ──────────────────────────────────────────────────────

def test_pod_with_no_status_does_not_crash():
    dep = _dep(1, 1, 1, 0)
    pod = MagicMock()
    pod.status = None
    assert compute_health(dep, [pod]) == HealthStatus.HEALTHY


def test_empty_pod_list_falls_through_to_replicas():
    dep = _dep(3, 3, 3, 0)
    assert compute_health(dep, []) == HealthStatus.HEALTHY
