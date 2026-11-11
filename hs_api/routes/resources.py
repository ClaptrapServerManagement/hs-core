import asyncpg
from fastapi import APIRouter, Depends

from ..auth import Caller, get_caller, require_admin, require_agent
from ..common import get_resource_row, resource_in_scope
from ..db import get_conn
from ..errors import ApiError
from ..models import ResourceCreateIn, ResourceKind, ResourceOut, ResourceUpdateIn, StatusReportIn

router = APIRouter(tags=["resources"])

_SELECT = """
SELECT r.name, r.kind::text AS kind, r.display_name, p.name AS parent,
       r.status::text AS status, r.status_detail, r.status_since, r.last_seen_at
  FROM resources r
  LEFT JOIN resources p ON p.id = r.parent_id
 WHERE r.enabled
"""

_DETAILS = {
    "host": """SELECT proxmox_node, host(ip_address) AS ip_address, mac_address::text AS mac_address,
                      relay_gpio_pin, power_sense_gpio_pin, relay_active_high,
                      power_on_press_ms, force_off_press_ms
                 FROM hosts WHERE resource_id = $1""",
    "vm": "SELECT proxmox_vmid, host(ip_address) AS ip_address FROM vms WHERE resource_id = $1",
    "service": "SELECT service_type, config FROM services WHERE resource_id = $1",
}

async def _fetch_one(conn: asyncpg.Connection, name: str, with_details: bool = True) -> dict:
    row = await conn.fetchrow(_SELECT + " WHERE r.name = $1", name)
    if row is None:
        raise ApiError(404, "resource_not_found", f"Ressource '{name}' gibt es nicht.")
    data = dict(row)
    if with_details:
        details = await conn.fetchrow(_DETAILS[data["kind"]], data["id"])
        data["details"] = dict(details) if details else None
    return data

@router.get("/resources", response_model=list[ResourceOut])
async def list_resources(
    kind: ResourceKind | None = None,
    caller: Caller = Depends(get_caller),
    conn: asyncpg.Connection = Depends(get_conn),
):
    # All resources sorted by status, optionally filtered by kind
    rows = await conn.fetch(
        _SELECT + " AND ($1::resource_kind IS NULL OR r.kind = $1::resource_kind)"
                  " ORDER BY r.kind, r.name",
        kind,
    )
    return [dict(r) for r in rows]

@router.get("resources/{name}", response_model=ResourceOut)
async def get_resource(
    name:str,
    caller: Caller = Depends(get_caller),
    conn: asyncpg.Connection = Depends(get_conn),
):
    return await _fetch_one(conn, name)

@router.post("/resources", response_model=ResourceOut, status_code=201)
async def create_resource(body: ResourceCreateIn, caller: Caller = Depends(require_admin), conn: asyncpg.Connection = Depends(get_conn)):
    # creates new ressource
    details = {"host": body.host, "vm": body.vm, "service": body.service}[body.kind]
    if details is None:
        raise ApiError(422, "details_required", f"Für kind '{body.kind}' fehlt das Feld '{body.kind}'.")

    async with conn.transaction():
        parent_id = None
        if body.parent is not None:
            parent_id = (await get_resource_row(conn, body.parent))["id"]
        resource_id = await conn.fetchval(
            """
            INSERT INTO resources (kind, parent_id, name, display_name)
            VALUES ($1::resource_kind, $2, $3, $4) RETURNING id
            """,
            body.kind, parent_id, body.name, body.display_name,
        )
        if body.kind == "host":
            h = body.host
            await conn.execute(
                """
                INSERT INTO hosts (resource_id, proxmox_node, ip_address, mac_address, relay_gpio_pin,
                                   power_sense_gpio_pin, relay_active_high, power_on_press_ms, force_off_press_ms)
                VALUES ($1, $2, $3::inet, $4::macaddr, $5, $6, $7, $8, $9)
                """,
                resource_id, h.proxmox_node, h.ip_address, h.mac_address, h.relay_gpio_pin,
                h.power_sense_gpio_pin, h.relay_active_high, h.power_on_press_ms, h.force_off_press_ms,
            )
        elif body.kind == "vm":
            await conn.execute(
                "INSERT INTO vms (resource_id, proxmox_vmid, ip_address) VALUES ($1, $2, $3::inet)",
                resource_id, body.vm.proxmox_vmid, body.vm.ip_address,
            )
        else:
            await conn.execute(
                "INSERT INTO services (resource_id, service_type, config) VALUES ($1, $2, $3)",
                resource_id, body.service.service_type, body.service.config,
            )
    return await _fetch_one(conn, body.name)


@router.patch("/resources/{name}", response_model=ResourceOut)
async def update_resource(name: str, body: ResourceUpdateIn, caller: Caller = Depends(require_admin),
                          conn: asyncpg.Connection = Depends(get_conn)):
    # Change display name or toggle
    fields = body.model_dump(exclude_unset=True)
    current = await _fetch_one(conn, name, with_details=False)
    await conn.execute(
        "UPDATE resources SET display_name = $2, enabled = $3 WHERE id = $1",
        current["id"],
        fields.get("display_name", current["display_name"]),
        fields.get("enabled", current["enabled"]),
    )
    return await _fetch_one(conn, name)

@router.get("/resources/{name}/status", response_model=ResourceOut)
async def report_status(
    name: str,
    body: StatusReportIn,
    caller: Caller = Depends(require_agent),
    conn: asyncpg.Connection = Depends(get_conn),
):
    # automatically changes 'status_changed'
    target = await get_resource_row(conn, name)
    if not await resource_in_scope(conn, caller, target["id"]):
        raise ApiError(403, "forbidden", f"'{caller.name}' ist für '{name}' nicht zuständig.")
    await conn.execute(
        """
        UPDATE resources
           SET status = $2::resource_status, status_detail = $3, last_seen_at = now()
         WHERE id = $1
        """,
        target["id"], body.status, body.detail,
    )
    return await _fetch_one(conn, name)
