import logging
import signal
import sys
import threading
import time

from . import __version__, config, relay
from .api_client import ApiClient, ApiError

log = logging.getLogger("hs-power-controller")

def execute(client: ApiClient, command: dict) -> None:
    action, target = command["action"], command["target"]
    log.info("Command %s: %s für %s", command["id"], action, target)
    try:
        if action == "host.power_on":
            # Safety (short press = graceful shutdwn)
            if client.get_resource(target)["status"] == "ON":
                raise RuntimeError(f"{target} ist bereits an")
            relay.press(config.POWER_ON_PRESS_SECONDS)
        elif action == "host.force_off":
            relay.press(config.FORCE_OFF_PRESS_SECONDS)
        else:
            raise RuntimeError(f"Action {action} kann der Power Controller nicht ausführen")
    except Exception as e:
        log.warning("Command %s fehlgeschlagen: %s", command["id"], e)
        client.report_result(command["id"], ok=False, error_message=str(e))
        return
    client.report_result(command["id"], ok=True)
    log.info("Command %s erledigt", command["id"])


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    if not config.API_TOKEN:
        log.error("HS_API_TOKEN ist nicht gesetzt.")
        sys.exit(1)

    client = ApiClient(config.API_URL, config.API_TOKEN)
    stop = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: stop.set())
    signal.signal(signal.SIGINT, lambda *_: stop.set())

    log.info("Start, Version %s, Relais an GPIO %s%s", __version__, config.RELAY_PIN,
             " (DRY RUN)" if config.DRY_RUN else "")
    last_heartbeat = 0.0
    last_ok = None

    while not stop.is_set():
        try:
            if time.monotonic() - last_heartbeat >= config.HEARTBEAT_SECONDS:
                client.heartbeat(__version__)
                last_heartbeat = time.monotonic()
            command = client.next_command()
            if command is not None:
                execute(client, command)
            if last_ok is not True:
                log.info("Verbindung zur API steht")
            last_ok = True
        except ApiError as e:
            if last_ok is not False:
                log.warning("API-Fehler: %s", e)
            last_ok = False
        stop.wait(config.POLL_SECONDS)

    log.info("Beendet.")

if __name__ == "__main__":
    main()
