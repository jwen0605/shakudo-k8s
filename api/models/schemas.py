import re
from typing import Optional, List, Dict
from pydantic import BaseModel, Field, field_validator, model_validator

_DNS_LABEL_RE = re.compile(r'^[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?$|^[a-z0-9]$')
_CPU_RE = re.compile(r'^\d+(\.\d+)?m?$')
_MEMORY_RE = re.compile(r'^\d+(\.\d+)?(Ki|Mi|Gi|Ti|Pi|Ei|K|M|G|T|P|E)?$')


class ResourceSpec(BaseModel):
    cpu: Optional[str] = None
    memory: Optional[str] = None

    @field_validator('cpu')
    @classmethod
    def validate_cpu(cls, v):
        if v is not None and not _CPU_RE.match(v):
            raise ValueError(f"Invalid CPU format '{v}'. Use e.g. '100m' or '0.5'")
        return v

    @field_validator('memory')
    @classmethod
    def validate_memory(cls, v):
        if v is not None and not _MEMORY_RE.match(v):
            raise ValueError(f"Invalid memory format '{v}'. Use e.g. '128Mi' or '1Gi'")
        return v


class Resources(BaseModel):
    requests: Optional[ResourceSpec] = None
    limits: Optional[ResourceSpec] = None


class EnvVar(BaseModel):
    name: str
    value: str


class DeploymentCreateRequest(BaseModel):
    name: str
    namespace: str = "default"
    image: str
    replicas: int = Field(default=1, ge=0)
    port: Optional[int] = Field(default=None, ge=1, le=65535)
    resources: Optional[Resources] = None
    env: Optional[List[EnvVar]] = Field(default_factory=list)
    labels: Optional[Dict[str, str]] = Field(default_factory=dict)
    command: Optional[List[str]] = None
    args: Optional[List[str]] = None

    @field_validator('name')
    @classmethod
    def validate_name(cls, v):
        if not v or not _DNS_LABEL_RE.match(v):
            raise ValueError(
                "Name must be DNS-compatible: lowercase alphanumeric and hyphens, "
                "start and end with alphanumeric, max 63 chars"
            )
        return v

    @field_validator('namespace')
    @classmethod
    def validate_namespace(cls, v):
        if not v or not _DNS_LABEL_RE.match(v):
            raise ValueError("Namespace must be a valid DNS label")
        return v

    @field_validator('image')
    @classmethod
    def validate_image(cls, v):
        if not v or not v.strip():
            raise ValueError("Image must not be empty")
        if ' ' in v or '\t' in v or '\n' in v:
            raise ValueError("Image must not contain whitespace")
        return v


class DeploymentUpdateRequest(BaseModel):
    replicas: Optional[int] = Field(default=None, ge=0)
    image: Optional[str] = None

    @field_validator('image')
    @classmethod
    def validate_image(cls, v):
        if v is not None and (not v.strip() or ' ' in v):
            raise ValueError("Invalid image format")
        return v

    @model_validator(mode='after')
    def check_at_least_one(self):
        if self.replicas is None and self.image is None:
            raise ValueError("At least one of 'replicas' or 'image' must be provided")
        return self



class ReplicaStatus(BaseModel):
    desired: int
    ready: int
    available: int
    unavailable: int


class DeploymentConditionOut(BaseModel):
    type: str
    status: str
    reason: Optional[str] = None
    message: Optional[str] = None
    last_transition_time: Optional[str] = None


class ContainerStateOut(BaseModel):
    state: str
    reason: Optional[str] = None
    message: Optional[str] = None
    started_at: Optional[str] = None
    exit_code: Optional[int] = None


class ContainerStatusOut(BaseModel):
    name: str
    image: str
    ready: bool
    restart_count: int
    state: Optional[ContainerStateOut] = None


class PodStatusOut(BaseModel):
    name: str
    phase: str
    node: Optional[str] = None
    restart_count: int
    containers: List[ContainerStatusOut]


class DeploymentResponse(BaseModel):
    id: str
    name: str
    namespace: str
    image: str
    replicas: ReplicaStatus
    health: str
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class DeploymentDetailResponse(DeploymentResponse):
    conditions: List[DeploymentConditionOut] = []
    pods: List[PodStatusOut] = []


class ErrorResponse(BaseModel):
    error: str
    detail: Optional[str] = None
