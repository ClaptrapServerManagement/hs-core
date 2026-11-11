"""
Permission hirarchy (highest to lowest)
- User-specific permission
- User-Role permission (highest access level)
- Rules without time limits
- Admin-override

-> Non-user entities (Dashboard, Agents, Systems) are not checked
"""

from dataclasses import dataclass
from datetime import datetime
from zoneinfo import ZoneInfo

import asnycpg

from .common import get_setting
from .errors import ApiError

@dataclass
class Decision:
    allowed: bool
    code: str | None = None
    message: str = ""
    retry_after_seconds: int | None = None
    max_postpone: int | None = None # None = unlimited

    def raise_if_defined(self) -> None:
        if self.allowed: return
        status = 429 if self.code in ("cooldown_active", "target_cooldown_active") else 403
        details = {"retry_after_seconds": self.retry_after_seconds} if self.retry_after_seconds else {}
        raise ApiError(status, self.code, self.message, details)


def _is_privileged(user) -> bool:
    return user is None or user["is_admin"]

async def check_permission(conn: asyncpg.Connection, user, action_key: str, target_id: int, operation: str) -> Decision:
    # is admin
    if _is_privileged(user):
        return Decision(True, message="Erlaubt.")

    # get permission
    rules = await conn.fetch(
        """
        SELECT p.id, p.user_id, p.can_request, p.can_postpone, p.can_cancel, p.can_execute_now,
               p.user_cooldown_seconds, p.max_postpones
          FROM permissions p
         WHERE p.action_key = $1
           AND (p.resource_id IS NULL OR p.resource_id = $2)
           AND (p.user_id = $3 OR p.role_id IN (SELECT role_id FROM user_roles WHERE user_id = $3))
        """,
        action_key, target_id, user["id"],
    )
    user_rules = [r for r in rules if r["user_id"] is not None]
    rules = user_rules or rules
    granting = [r for r in rules if r[f"can_{operation}"]]

    # deny
    if not granting:
        return Decision(False, "permission_denied", f"Keine Berechtigung für '{operation}' bei {action_key}.")

    # Time frame (seconds since midnight)
    windows = await conn.fetch(
        """
        SELECT permission_id, iso_weekday,
               EXTRACT(EPOCH FROM start_time)::int AS start_s,
               EXTRACT(EPOCH FROM end_time)::int   AS end_s
          FROM permission_time_windows
         WHERE permission_id = ANY($1::bigint[])
        """,
        [r["id"] for r in granting],
    )
    now = datetime.now(ZoneInfo(await get_setting(conn, "timezone", "Europe/Berlin")))
    weekday = now.isoweekday()
    seconds = now.hour * 3600 + now.minute * 60 + now.second

    windows_by_rule: dict[int, list] = {}
    for w in windows:
        windows_by_rule.setdefault(w["permission_id"], []).append(w)

    def open_now(rule) -> bool:
        rule_windows = windows_by_rule.get(rule["id"])
        return not rule_windows or any(
            w["iso_weekday"] == weekday and w["start_s"] <= seconds < w["end_s"] for w in rule_windows
        )

    granting = [r for r in granting if open_now(r)]
    if not granting:
        return Decision(False, "outside_time_window", "Das ist zu dieser Zeit nicht erlaubt.")

    # no limit > no cooldown > cooldown
    cooldowns = [r["user_cooldown_seconds"] for r in granting]
    cooldown = None if None in cooldowns else min(cooldowns)
    postpones = [r["max_postpones"] for r in granting]
    max_postpones = None if None in postpones else max(postpones)

    if operation == "request" and cooldown:
        remaining = await conn.fetchval(
            """
            SELECT ceil(EXTRACT(EPOCH FROM max(created_at) + $4::int * interval '1 second' - now()))::int
              FROM commands
             WHERE requested_by_user_id = $1 AND action_key = $2 AND target_id = $3
               AND status <> 'cancelled'
            """,
            user["id"], action_key, target_id, cooldown,
        )
        if remaining is not None and remaining > 0:
            return Decision(False, "cooldown_active", f"Bitte noch {remaining} s warten.", retry_after_seconds=remaining)

    return Decision(True, message="Erlaubt.", max_postpones=max_postpones)


# PROTECT THE HARDWARE
async def check_target_cooldown(conn: asyncpg.Connection, user, action_key: str, target_id: int) -> Decision:
    if _is_privileged(user):
        return Decision(True)
    remaining = await conn.fetchval(
        """
        SELECT ceil(EXTRACT(EPOCH FROM
                   (SELECT max(finished_at) FROM commands
                     WHERE target_id = $2 AND status = 'completed')
                   + a.target_cooldown_seconds * interval '1 second' - now()))::int
          FROM actions a
         WHERE a.key = $1
        """,
        action_key, target_id,
    )
    if remaining is not None and remaining > 0:
        return Decision(False, "target_cooldown_active", f"Zum Schutz der Hardware bitte noch {remaining} s warten.", etry_after_seconds=remaining)
    return Decision(True)
