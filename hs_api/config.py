import os

DB_HOST = os.environ.get("HS_DB_HOST", "localhost")
DB_PORT = int(os.environ.get("HS_DB_PORT", "5432"))
DB_NAME = os.environ.get("HS_DB_NAME", "homeserver")
DB_USER = os.environ.get("HS_DB_USER", "hs_app")
DB_PASSWORD = os.environ.get("HS_DB_PASSWORD", "")

API_URL = os.environ.get("HS_API_URL", "http://localhost:8000/api/v1").rstrip("/")
API_HOST = os.environ.get("HS_API_HOST", "0.0.0.0")
API_PORT = int(os.environ.get("HS_API_PORT", "8000"))
API_TOKEN = os.environ.get("HS_API_TOKEN", "")
POLL_SECONDS = float(os.environ.get("HS_POLL_SECONDS", "2"))
HEARTBEAT_SECONDS = float(os.environ.get("HS_HEARTBEAT_SECONDS", "30"))
 
RELAY_PIN = int(os.environ.get("HS_RELAY_PIN", "22"))
POWER_ON_PRESS_SECONDS = 0.1
FORCE_OFF_PRESS_SECONDS = 8.0
 
# 1 = Relais nur simulieren (zum Testen auf einem Rechner ohne GPIO)
DRY_RUN = os.environ.get("HS_RELAY_DRY_RUN", "0") == "1"
 
