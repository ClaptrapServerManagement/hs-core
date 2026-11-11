import os

API_URL = os.environ.get("HS_API_URL", "http://localhost:8000/api/v1").rstrip("/")
API_TOKEN = os.environ.get("HS_API_TOKEN", "")
POLL_SECONDS = float(os.environ.get("HS_POLL_SECONDS", "2"))
HEARTBEAT_SECONDS = float(os.environ.get("HS_HEARTBEAT_SECONDS", "30"))

RELAY_PIN = int(os.environ.get("HS_RELAY_PIN", "22"))
POWER_ON_PRESS_SECONDS = 0.1
FORCE_OFF_PRESS_SECONDS = 8.0

# 1 = simulate relais
DRY_RUN = os.environ.get("HS_RELAY_DRY_RUN", "0") == "1"
