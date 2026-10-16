#Legt eine Komponente an bzw. erneuert ihr Token und gibt das Token EINMALIG aus.

"""
Beispiele:
    python -m hs_api.tools.create_component host_agent hs-host-agent@pve01 --resource pve01
    python -m hs_api.tools.create_component power_controller hs-power-controller
    python -m hs_api.tools.create_component discord_bot hs-discord-bot
"""

import argparse
import asyncio
import sys

import asyncpg

from .. import config
from ..auth import generate_token, hash_token

KINDS = ["api", "discord_bot", "power_controller", "dashboard",
         "host_agent", "vm_agent", "service_manager"]


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("kind", choices=KINDS)
    parser.add_argument("name", help="Name laut Nomenklatur, z.B. hs-host-agent@pve01")
    parser.add_argument("--resource", help="Ressource, auf der die Komponente läuft, z.B. pve01")
    args = parser.parse_args()

    conn = await asyncpg.connect(
        host=config.DB_HOST, port=config.DB_PORT, database=config.DB_NAME,
        user=config.DB_USER, password=config.DB_PASSWORD,
    )
    try:
        resource_id = None
        if args.resource:
            resource_id = await conn.fetchval("SELECT id FROM resources WHERE name = $1", args.resource)
            if resource_id is None:
                sys.exit(f"Ressource '{args.resource}' gibt es nicht.")

        token = generate_token()
        existed = await conn.fetchval("SELECT EXISTS (SELECT 1 FROM components WHERE name = $1)", args.name)
        await conn.execute(
            """
            INSERT INTO components (kind, name, resource_id, api_token_hash)
            VALUES ($1::component_kind, $2, $3, $4)
            ON CONFLICT (name) DO UPDATE
               SET api_token_hash = EXCLUDED.api_token_hash,
                   resource_id = COALESCE(EXCLUDED.resource_id, components.resource_id)
            """,
            args.kind, args.name, resource_id, hash_token(token),
        )
    finally:
        await conn.close()

    action = "Token erneuert für" if existed else "Komponente angelegt:"
    print(f"{action} {args.name}", file=sys.stderr)
    print("Token (wird nicht gespeichert, jetzt notieren):", file=sys.stderr)
    print(token)


if __name__ == "__main__":
    asyncio.run(main())
