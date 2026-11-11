from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field

SNAKE_CASE = r"^[a-z][a-z0-9_]*$"
KEBAB_NAME = r"^[a-z0-9][a-z0-9-]*$"
CLOCK_TIME = r"^([01]\d|2[0-3]):[0-5]\d$|^24:00$"

# ======
# ENUMS
# ======
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

class CommandStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class ScheduledActionStatus(StrEnum):
    SCHEDULED = "scheduled"
    EXECUTED = "executed"
    CANCELLED = "cancelled"
    FAILED = "failed"

class Operation(StrEnum):
    REQUEST = "request"
    POSTPONE = "postpone"
    CANCEL = "cancel"
    EXECUTE_NOW = "execute_now"

# ======
# SHARED
# ======

class IdentifyRef(BaseModel):
    provider: str = Field(examples=["discord"])
    external_id: str = Field(examples=["123456789012345678"])

class ActorIn(BaseModel):
    requested_by: IdentifyRef | None = None

# ======
# COMPONENTS
# ======

class HeartbeatIn(BaseModel):
    version: str | None = Field(default=None, max_length=50)

class ComponentOut(BaseModel):
    id: int
    kind: str
    name: str
    resource: str | None = None
    status: CommandStatus
    version: str | None
    last_heartbeat_at: datetime | None

# ======
# RESSOURCES
# ======
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
    enabled: bool
    details: dict[str, Any] | None = None

class HostDetailsIn(BaseModel):
    proxmox_node: str
    ip_address: str | None = None
    mac_address: str | None = None
    relay_gpio_pin: int | None = None
    power_sense_gpio_pin: int | None = None
    relay_active_high: bool = True
    power_on_press_ms: int = 100
    force_off_press_ms: int = 8000

class VmDetailsIn(BaseModel):
    proxmox_vmid: int
    ip_address: str | None = None

class ServiceDetailsIn(BaseModel):
    service_type: str = Field(pattern=SNAKE_CASE)
    config: dict[str, Any] = Field(default_factory=dict)

class ResourceCreateIn(BaseModel):
    kind: ResourceKind
    name: str = Field(pattern=KEBAB_NAME, max_length=50, examples=["vm-example"])
    display_name: str | None = None
    parent: str | None = Field(default=None, examples=["pve01"])
    host: HostDetailsIn | None = None
    vm: VmDetailsIn | None = None
    service: ServiceDetailsIn | None = None

class ResourceUpdateIn(BaseModel):
    display_name: str | None = None
    enabled: bool | None = None

# ======
# ACTIONS
# ======
class ActionOut(BaseModel):
    key: str
    target_kind: ResourceKind
    description: str
    is_read_only: bool
    target_cooldown_seconds: int
    executor: str | None

# ======
# COMMANDS
# ======
class CommandIn(BaseModel):
    action: str = Field(examples=["host.power_on"])
    target: str = Field(examples=["pve01"])
    requested_by: IdentityRef | None = None
    parameters: dict[str, Any] = Field(default_factory=dict)

class CommandResultIn(BaseModel):
    status: CommandStatus = Field(examples=["completed"])  # nur completed oder failed erlaubt
    result: dict[str, Any] | None = None
    error_message: str | None = Field(default=None, max_length=1000)

class CommandOut(BaseModel):
    id: int
    action: str
    target: str
    source: str
    requested_by: str | None
    scheduled_action_id: int | None
    status: CommandStatus
    parameters: dict[str, Any]
    result: dict[str, Any] | None
    error_message: str | None
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None

# ======
# SCHEDULED ACTIONS
# ======
class ScheduledActionIn(BaseModel):
    action: str = Field(examples=["host.shutdown"])
    target: str = Field(examples=["pve01"])
    # Entweder fester Zeitpunkt oder "in X Minuten"
    execute_at: datetime | None = None
    in_minutes: int | None = Field(default=None, ge=1, le=7 * 24 * 60)
    requested_by: IdentityRef | None = None

class PostponeIn(BaseModel):
    minutes: int | None = Field(default=None, ge=1, le=24 * 60,
                                description="Leer = default_postpone_minutes aus den Settings")
    requested_by: IdentityRef | None = None

class AnnouncedIn(BaseModel):
    discord_message_id: str | None = None

class ScheduledActionOut(BaseModel):
    id: int
    action: str
    target: str
    reason: str
    status: ScheduledActionStatus
    execute_at: datetime
    original_execute_at: datetime
    postpone_count: int
    announced_at: datetime | None
    discord_message_id: str | None
    created_by: str | None
    cancelled_by: str | None
    cancel_reason: str | None
    command_id: int | None
    created_at: datetime

# ======
# USE CASES
# ======
class UseCaseReport(BaseModel):
    kind: str = Field(pattern=SNAKE_CASE, examples=["minecraft_player"])
    identifier: str = Field(default="", max_length=200, examples=["Steve"])

class UseCaseSyncIn(BaseModel):
    use_cases: list[UseCaseReport]

class UseCaseOut(BaseModel):
    id: int
    resource: str
    kind: str
    identifier: str
    started_at: datetime
    last_seen_at: datetime
    ended_at: datetime | None

# ======
# EVENTS
# ======
class EventOut(BaseModel):
    id: int
    occurred_at: datetime
    event_type: str
    severity: str
    resource: str | None
    command_id: int | None
    scheduled_action_id: int | None
    user: str | None
    component: str | None
    message: str | None
    data: dict[str, Any]

# ======
# USERS, ROLES, PERMISSIONS
# ======
class IdentityIn(IdentityRef):
    external_name: str | None = None

class IdentityOut(IdentityIn):
    pass

class UserCreateIn(BaseModel):
    display_name: str = Field(min_length=1, max_length=100)
    is_admin: bool = False
    note: str | None = None
    identities: list[IdentityIn] = Field(default_factory=list)
    roles: list[str] = Field(default_factory=list, description="Rollennamen")

class UserUpdateIn(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=100)
    is_admin: bool | None = None
    is_active: bool | None = None
    note: str | None = None

class UserRolesIn(BaseModel):
    roles: list[str]

class UserOut(BaseModel):
    id: int
    display_name: str
    is_admin: bool
    is_active: bool
    note: str | None
    identities: list[IdentityOut]
    roles: list[str]

class RoleIn(BaseModel):
    name: str = Field(pattern=KEBAB_NAME, max_length=50, examples=["minecraft-spieler"])
    description: str | None = None
    discord_role_id: str | None = None

class RoleUpdateIn(BaseModel):
    name: str | None = Field(default=None, pattern=KEBAB_NAME, max_length=50)
    description: str | None = None
    discord_role_id: str | None = None

class RoleOut(RoleIn):
    id: int
    members: int

class TimeWindow(BaseModel):
    iso_weekday: int = Field(ge=1, le=7, description="1 = Montag ... 7 = Sonntag")
    start: str = Field(pattern=CLOCK_TIME, examples=["18:00"])
    end: str = Field(pattern=CLOCK_TIME, examples=["24:00"])

class PermissionIn(BaseModel):
    role: str | None = Field(default=None, description="Rollenname, ODER user_id")
    user_id: int | None = None
    action: str = Field(examples=["host.power_on"])
    target: str | None = Field(default=None, description="Leer = alle passenden Ressourcen")
    can_request: bool = False
    can_postpone: bool = False
    can_cancel: bool = False
    can_execute_now: bool = False
    user_cooldown_seconds: int | None = Field(default=None, ge=0)
    max_postpones: int | None = Field(default=None, ge=0)
    time_windows: list[TimeWindow] = Field(default_factory=list,
                                           description="Leer = jederzeit erlaubt")

class PermissionOut(BaseModel):
    id: int
    role: str | None
    user_id: int | None
    user: str | None
    action: str
    target: str | None
    can_request: bool
    can_postpone: bool
    can_cancel: bool
    can_execute_now: bool
    user_cooldown_seconds: int | None
    max_postpones: int | None
    time_windows: list[TimeWindow]

class PermissionCheckIn(BaseModel):
    requested_by: IdentityRef
    action: str = Field(examples=["host.power_on"])
    target: str = Field(examples=["pve01"])
    operation: Operation = Operation.REQUEST

class PermissionCheckOut(BaseModel):
    allowed: bool
    code: str | None
    message: str
    retry_after_seconds: int | None
    max_postpones: int | None

# ======
# SETTINGS
# ======
class SettingOut(BaseModel):
    key: str
    value: Any
    description: str | None
    updated_at: datetime

class SettingIn(BaseModel):
    value: Any
