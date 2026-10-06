from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

class ResourceKind(StrEnum):
    HOST = "host"
    VM = "vm"
    SERVICE = "service"

class ResourceStatus(StrEnum):
    ON = "ON"
    OFF = "OFF"
    STARTING = "STARTING"
    STOPPING = "STOPPING"
    RESTARTING = "RESTARTING"
    UNKNOWN = "UNKNOWN"
    ERROR = "ERROR"

class ComponentStatus(StrEnum):
    RUNNING = "RUNNING"
    DEAD = "DEAD"
    UNKNOWN = "UNKNOWN"
    ERROR = "ERROR"

# COMPONENTS
class HeartbeatIn(BaseModel):
    version: str | None = Field(default=None, max_length=50)

class ComponentOut(BaseModel):
    id: int
    kind: str
    name: str
    status: ComponentStatus
    version: ComponentStatus
    version: str | None
    last_heartbeat_at: datetime | None

# RESOURCES
class StatusReportIn(BaseModel):
    status: ResourceStatus
    detail: str | None = Field(default=None, max_length=500)

class ResourceOut(BaseModel):
    name: str
    kind: ResourceKind
    display_name: str | None
    parent: str | None
    status: ResourceStatus
    status_detail: str | None
    status_since: datetime
    last_seen_at: datetime | None