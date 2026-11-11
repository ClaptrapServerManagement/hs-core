import json
import urllib.error
import urllib.request

class ApiError(Exception):
    pass

class ApiClient:
    def __init__(self, base_url: str, token: str, timeout: float = 10):
        self.base_url = base_url
        self.token = token
        self.timeout = timeout

    def _request(self, method: str, path: str, body: dict | None = None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            self.base_url + path,
            data=data,
            method=method,
            headers={
                "Authorization": f"Bearer {self.token}",
                "Content-Type": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            try:
                error = json.loads(e.read())["error"]
                message = f"{error['code']}: {error['message']}"
            except Exception:
                message = f"HTTP {e.code}"
            raise ApiError(message) from None
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise ApiError(f"API nicht erreichbar ({e})") from None

    def heartbeat(self, version: str) -> dict:
        return self._request("POST", "/components/heartbeat", {"version": version})

    def report_status(self, resource: str, status: str, detail: str | None = None) -> dict:
        return self._request("PUT", f"/resources/{resource}/status", {"status": status, "detail": detail})

    def get_resource(self, name: str) -> dict:
        return self._request("GET", f"/resources/{name}")

    def next_command(self) -> dict | None:
        """Nächster Command oder None, wenn nichts zu tun ist (HTTP 204)."""
        return self._request("GET", "/commands/next")

    def report_result(self, command_id: int, ok: bool, error_message: str | None = None) -> dict:
        body = {"status": "completed" if ok else "failed", "error_message": error_message}
        return self._request("POST", f"/commands/{command_id}/result", body)
