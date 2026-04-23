import datetime
from typing import Optional, List

from fastapi import Depends, HTTPException
from kubernetes import client
from kubernetes.client.exceptions import ApiException

from api.k8s.client import get_apps_v1, get_core_v1
from api.k8s.health import compute_health
from api.models.schemas import (
    DeploymentCreateRequest,
    DeploymentUpdateRequest,
    DeploymentResponse,
    DeploymentDetailResponse,
    ReplicaStatus,
    DeploymentConditionOut,
    ContainerStatusOut,
    ContainerStateOut,
    PodStatusOut,
)

MANAGED_BY_LABEL = "app.kubernetes.io/managed-by"
MANAGED_BY_VALUE = "shakudo-k8s"
MANAGED_SELECTOR = f"{MANAGED_BY_LABEL}={MANAGED_BY_VALUE}"


def _resource_map(spec) -> Optional[dict]:
    if spec is None:
        return None
    m = {k: v for k, v in (("cpu", spec.cpu), ("memory", spec.memory)) if v}
    return m or None


class DeploymentService:
    def __init__(self, apps_v1: client.AppsV1Api, core_v1: client.CoreV1Api):
        self.apps = apps_v1
        self.core = core_v1

    def _ensure_namespace(self, namespace: str) -> None:
        try:
            self.core.read_namespace(namespace)
        except ApiException as e:
            if e.status == 404:
                try:
                    self.core.create_namespace(
                        client.V1Namespace(
                            metadata=client.V1ObjectMeta(name=namespace)
                        )
                    )
                except ApiException as ce:
                    raise HTTPException(500, detail=f"Failed to create namespace: {ce.reason}")
            else:
                raise HTTPException(500, detail=f"K8s API error: {e.reason}")

    def _find_by_uid(self, uid: str) -> Optional[client.V1Deployment]:
        try:
            deps = self.apps.list_deployment_for_all_namespaces(
                label_selector=MANAGED_SELECTOR
            )
        except ApiException as e:
            raise HTTPException(500, detail=f"K8s API error: {e.reason}")
        for dep in deps.items:
            if str(dep.metadata.uid) == uid:
                return dep
        return None

    def _require_by_uid(self, uid: str) -> client.V1Deployment:
        dep = self._find_by_uid(uid)
        if dep is None:
            raise HTTPException(404, detail=f"Deployment with id '{uid}' not found")
        return dep

    def _get_pods(self, dep: client.V1Deployment) -> List[client.V1Pod]:
        selector = dep.spec.selector.match_labels or {}
        label_str = ",".join(f"{k}={v}" for k, v in selector.items())
        try:
            pods = self.core.list_namespaced_pod(
                dep.metadata.namespace,
                label_selector=label_str,
            )
            return pods.items
        except ApiException:
            return []

    @staticmethod
    def _image_from_deployment(dep: client.V1Deployment) -> str:
        containers = dep.spec.template.spec.containers or []
        return containers[0].image if containers else ""

    @staticmethod
    def _replica_status(dep: client.V1Deployment) -> ReplicaStatus:
        s = dep.status or client.V1DeploymentStatus()
        desired = dep.spec.replicas or 0
        return ReplicaStatus(
            desired=desired,
            ready=s.ready_replicas or 0,
            available=s.available_replicas or 0,
            unavailable=s.unavailable_replicas or 0,
        )

    @staticmethod
    def _latest_update_time(dep: client.V1Deployment) -> Optional[str]:
        conditions = (dep.status or client.V1DeploymentStatus()).conditions or []
        times = [c.last_update_time for c in conditions if c.last_update_time]
        if not times:
            return None
        return max(times).isoformat()

    @staticmethod
    def _serialise_pod(pod) -> PodStatusOut:
        pod_status = pod.status or client.V1PodStatus()
        containers_out: List[ContainerStatusOut] = []
        total_restarts = 0

        for cs in pod_status.container_statuses or []:
            rc = cs.restart_count or 0
            total_restarts += rc
            state_out: Optional[ContainerStateOut] = None
            if cs.state:
                s = cs.state
                if s.running:
                    started = s.running.started_at
                    state_out = ContainerStateOut(
                        state="running",
                        started_at=started.isoformat() if started else None,
                    )
                elif s.waiting:
                    state_out = ContainerStateOut(
                        state="waiting",
                        reason=s.waiting.reason,
                        message=s.waiting.message,
                    )
                elif s.terminated:
                    state_out = ContainerStateOut(
                        state="terminated",
                        reason=s.terminated.reason,
                        exit_code=s.terminated.exit_code,
                    )
            containers_out.append(
                ContainerStatusOut(
                    name=cs.name,
                    image=cs.image or "",
                    ready=cs.ready or False,
                    restart_count=rc,
                    state=state_out,
                )
            )

        node = pod.spec.node_name if pod.spec else None
        return PodStatusOut(
            name=pod.metadata.name,
            phase=pod_status.phase or "Unknown",
            node=node,
            restart_count=total_restarts,
            containers=containers_out,
        )

    def _to_response(self, dep: client.V1Deployment, pods: List) -> DeploymentResponse:
        ts = dep.metadata.creation_timestamp
        return DeploymentResponse(
            id=str(dep.metadata.uid),
            name=dep.metadata.name,
            namespace=dep.metadata.namespace,
            image=self._image_from_deployment(dep),
            replicas=self._replica_status(dep),
            health=compute_health(dep, pods).value,
            created_at=ts.isoformat() if ts else None,
            updated_at=self._latest_update_time(dep),
        )

    def _to_detail(self, dep: client.V1Deployment, pods: List) -> DeploymentDetailResponse:
        base = self._to_response(dep, pods)
        conditions_out = [
            DeploymentConditionOut(
                type=c.type,
                status=c.status,
                reason=c.reason,
                message=c.message,
                last_transition_time=(
                    c.last_transition_time.isoformat() if c.last_transition_time else None
                ),
            )
            for c in ((dep.status or client.V1DeploymentStatus()).conditions or [])
        ]
        return DeploymentDetailResponse(
            **base.model_dump(),
            conditions=conditions_out,
            pods=[self._serialise_pod(p) for p in pods],
        )

    @staticmethod
    def _build_body(req: DeploymentCreateRequest) -> client.V1Deployment:
        base_labels = {
            "app": req.name,
            MANAGED_BY_LABEL: MANAGED_BY_VALUE,
        }
        user_labels = req.labels or {}
        pod_labels = {**base_labels, **user_labels}

        container = client.V1Container(name=req.name, image=req.image)

        if req.port:
            container.ports = [client.V1ContainerPort(container_port=req.port)]

        if req.env:
            container.env = [
                client.V1EnvVar(name=e.name, value=e.value) for e in req.env
            ]

        if req.resources:
            container.resources = client.V1ResourceRequirements(
                requests=_resource_map(req.resources.requests),
                limits=_resource_map(req.resources.limits),
            )

        if req.command:
            container.command = req.command
        if req.args:
            container.args = req.args

        return client.V1Deployment(
            metadata=client.V1ObjectMeta(
                name=req.name,
                namespace=req.namespace,
                labels=pod_labels,
            ),
            spec=client.V1DeploymentSpec(
                replicas=req.replicas,
                selector=client.V1LabelSelector(
                    match_labels={
                        "app": req.name,
                        MANAGED_BY_LABEL: MANAGED_BY_VALUE,
                    }
                ),
                template=client.V1PodTemplateSpec(
                    metadata=client.V1ObjectMeta(labels=pod_labels),
                    spec=client.V1PodSpec(containers=[container]),
                ),
            ),
        )

    # ── Public API ───────────────────────────────────────────────────────────

    def create(self, req: DeploymentCreateRequest) -> DeploymentResponse:
        self._ensure_namespace(req.namespace)

        # 409 if deployment already exists
        try:
            self.apps.read_namespaced_deployment(req.name, req.namespace)
            raise HTTPException(
                409,
                detail=f"Deployment '{req.name}' already exists in namespace '{req.namespace}'",
            )
        except ApiException as e:
            if e.status != 404:
                raise HTTPException(500, detail=f"K8s API error: {e.reason}")

        body = self._build_body(req)
        try:
            dep = self.apps.create_namespaced_deployment(req.namespace, body)
        except ApiException as e:
            if e.status == 422:
                raise HTTPException(400, detail=f"Invalid deployment spec: {e.body}")
            raise HTTPException(500, detail=f"K8s API error: {e.reason}")

        return self._to_response(dep, [])

    def list_deployments(self, namespace: Optional[str] = None) -> List[DeploymentResponse]:
        try:
            if namespace:
                result = self.apps.list_namespaced_deployment(
                    namespace, label_selector=MANAGED_SELECTOR
                )
            else:
                result = self.apps.list_deployment_for_all_namespaces(
                    label_selector=MANAGED_SELECTOR
                )
        except ApiException as e:
            if e.status == 404:
                return []
            raise HTTPException(500, detail=f"K8s API error: {e.reason}")

        return [self._to_response(dep, self._get_pods(dep)) for dep in result.items]

    def get(self, uid: str) -> DeploymentDetailResponse:
        dep = self._require_by_uid(uid)
        return self._to_detail(dep, self._get_pods(dep))

    def update(self, uid: str, req: DeploymentUpdateRequest) -> DeploymentResponse:
        dep = self._require_by_uid(uid)

        patch: dict = {"spec": {}}
        if req.replicas is not None:
            patch["spec"]["replicas"] = req.replicas
        if req.image is not None:
            container_name = dep.spec.template.spec.containers[0].name
            patch["spec"]["template"] = {
                "spec": {"containers": [{"name": container_name, "image": req.image}]}
            }

        try:
            updated = self.apps.patch_namespaced_deployment(
                dep.metadata.name, dep.metadata.namespace, patch
            )
        except ApiException as e:
            raise HTTPException(500, detail=f"K8s API error: {e.reason}")

        return self._to_response(updated, self._get_pods(updated))

    def delete(self, uid: str) -> None:
        dep = self._require_by_uid(uid)
        try:
            self.apps.delete_namespaced_deployment(
                dep.metadata.name,
                dep.metadata.namespace,
                body=client.V1DeleteOptions(propagation_policy="Foreground"),
            )
        except ApiException as e:
            raise HTTPException(500, detail=f"K8s API error: {e.reason}")

    def restart(self, uid: str) -> DeploymentResponse:
        dep = self._require_by_uid(uid)
        now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        patch = {
            "spec": {
                "template": {
                    "metadata": {
                        "annotations": {"kubectl.kubernetes.io/restartedAt": now}
                    }
                }
            }
        }
        try:
            updated = self.apps.patch_namespaced_deployment(
                dep.metadata.name, dep.metadata.namespace, patch
            )
        except ApiException as e:
            raise HTTPException(500, detail=f"K8s API error: {e.reason}")

        return self._to_response(updated, self._get_pods(updated))


# ── FastAPI dependency ───────────────────────────────────────────────────────

def get_deployment_service(
    apps_v1: client.AppsV1Api = Depends(get_apps_v1),
    core_v1: client.CoreV1Api = Depends(get_core_v1),
) -> DeploymentService:
    return DeploymentService(apps_v1, core_v1)
