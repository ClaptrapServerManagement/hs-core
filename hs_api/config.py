import os

DB_HOST = os.environ.get("HS_DB_HOST", "localhost")
DB_PORT = int(os.environ.get("HS_DB_PORT", "5432"))
DB_NAME = os.environ.get("HS_DB_NAME", "homeserver")
DB_USER = os.environ.get("HS_DB_USER", "hs_app")
DB_PASSWORD = os.environ.get("HS_DB_PASSWORD", "")

API_HOST = os.environ.get("HS_API_HOST", "0.0.0.0")
API_PORT = int(os.environ.get("HS_API_PORT", "8000"))