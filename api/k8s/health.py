from enum import Enum
from typing import List, Optional

# Container waiting reasons that indicate a failing deployment
_FAILING_REASONS = frozenset({
    "CrashLoopBackOff",
    "ImagePullBackOff",
    "ErrImagePull",
    "InvalidImageName",
    "OOMKilled",
})


class HealthStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    FAILING = "FAILING"
    PROGRESSING = "PROGRESSING"
    UNKNOWN = "UNKNOWN"


def compute_health(deployment, pods: Optional[List] = None) -> HealthStatus:
    """
    Derives a single health enum from a K8s Deployment object and its pods.

    Priority order:
      1. Crash/pull failures in any pod container → FAILING
      2. Active rollout in progress condition     → PROGRESSING
      3. desired == 0                            → HEALTHY (intentional scale-down)
      4. ready == desired                        → HEALTHY
      5. ready == 0                              → FAILING
      6. 0 < ready < desired                    → DEGRADED
      7. Otherwise                               → UNKNOWN
    """
    if deployment is None:
        return HealthStatus.UNKNOWN

    status = deployment.status
    if status is None:
        return HealthStatus.UNKNOWN

    desired: int = deployment.spec.replicas or 0
    ready: int = status.ready_replicas or 0

    # 1. Pod-level crash / image-pull failures
    if pods:
        for pod in pods:
            pod_status = pod.status
            if not pod_status:
                continue
            for cs in pod_status.container_statuses or []:
                if cs.state and cs.state.waiting:
                    if cs.state.waiting.reason in _FAILING_REASONS:
                        return HealthStatus.FAILING

    # 2. Rollout in progress
    conditions = {c.type: c for c in (status.conditions or [])}
    progressing = conditions.get("Progressing")
    if progressing and progressing.status == "True":
        if progressing.reason in ("ReplicaSetUpdated", "NewReplicaSetCreated"):
            return HealthStatus.PROGRESSING

    # 3–6. Replica counts
    if desired == 0:
        return HealthStatus.HEALTHY
    if ready == desired:
        return HealthStatus.HEALTHY
    if ready == 0:
        return HealthStatus.FAILING
    if 0 < ready < desired:
        return HealthStatus.DEGRADED

    return HealthStatus.UNKNOWN
