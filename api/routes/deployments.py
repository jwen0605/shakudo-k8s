from typing import Optional

from fastapi import APIRouter, Depends, Query

from api.k8s.deployments import DeploymentService, get_deployment_service
from api.models.schemas import DeploymentCreateRequest, DeploymentUpdateRequest

router = APIRouter(prefix="/api/deployments", tags=["deployments"])


@router.post("", status_code=201)
def create_deployment(
    req: DeploymentCreateRequest,
    svc: DeploymentService = Depends(get_deployment_service),
):
    return svc.create(req)


@router.get("")
def list_deployments(
    namespace: Optional[str] = Query(None, description="Filter by namespace"),
    svc: DeploymentService = Depends(get_deployment_service),
):
    return svc.list_deployments(namespace)


@router.get("/{uid}")
def get_deployment(
    uid: str,
    svc: DeploymentService = Depends(get_deployment_service),
):
    return svc.get(uid)


@router.patch("/{uid}")
def update_deployment(
    uid: str,
    req: DeploymentUpdateRequest,
    svc: DeploymentService = Depends(get_deployment_service),
):
    return svc.update(uid, req)


@router.delete("/{uid}", status_code=204)
def delete_deployment(
    uid: str,
    svc: DeploymentService = Depends(get_deployment_service),
):
    svc.delete(uid)


@router.post("/{uid}/restart")
def restart_deployment(
    uid: str,
    svc: DeploymentService = Depends(get_deployment_service),
):
    return svc.restart(uid)
