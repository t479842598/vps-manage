"""
vps-dashboard server — lightweight project dashboard for VPS.
Listens on 127.0.0.1:9090 only. Reverse-proxied by Nginx.
"""
from __future__ import annotations

import json
import subprocess
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOST = "127.0.0.1"
PORT = 9090
PROJECTS_FILE = Path(__file__).resolve().parent / "projects.json"
HTML_FILE = Path(__file__).resolve().parent / "index.html"
CACHE_SECONDS = 5

_pid_cache: dict[str, tuple[float, str | None]] = {}


def _run(cmd: list[str], timeout: float = 5.0) -> str:
    """Run a shell command, return stripped stdout or empty string on failure."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.stdout.strip()
    except Exception:
        return ""


def _human_duration(seconds: float) -> str:
    """Convert seconds to human-readable duration like '3天 12小时 45分钟'."""
    if seconds < 0:
        return "N/A"
    days, rem = divmod(int(seconds), 86400)
    hours, rem = divmod(rem, 3600)
    minutes = rem // 60
    parts = []
    if days:
        parts.append(f"{days}天")
    if hours:
        parts.append(f"{hours}小时")
    if minutes or not parts:
        parts.append(f"{minutes}分钟")
    return " ".join(parts)


def _human_memory(bytes_val: int) -> str:
    """Convert bytes to human-readable memory string."""
    if bytes_val <= 0:
        return "N/A"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(bytes_val) < 1024.0:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.1f} PB"


def _get_pid(service_name: str) -> str | None:
    """Get MainPID for a systemd service with 5-second cache."""
    now = time.time()
    cached = _pid_cache.get(service_name)
    if cached and (now - cached[0]) < CACHE_SECONDS:
        return cached[1]
    pid = _run(["systemctl", "show", service_name, "--property=MainPID", "--value"])
    if pid and pid != "0":
        _pid_cache[service_name] = (now, pid)
        return pid
    _pid_cache[service_name] = (now, None)
    return None


def _collect_project(proj: dict) -> dict:
    """Enrich a project dict with live data from the VPS."""
    result = {
        "name": proj.get("name", ""),
        "port": proj.get("port"),
        "path": proj.get("path", ""),
        "description": proj.get("description", ""),
        "github_url": proj.get("github_url") or None,
        "service_name": proj.get("service_name") or None,
        "domain": proj.get("domain") or None,
        "status": "unknown",
        "memory_bytes": None,
        "memory_human": None,
        "uptime_seconds": None,
        "uptime_human": None,
        "created_at": None,
        "port_active": False,
    }

    svc = result["service_name"]
    if not svc:
        return result

    # Status: active / inactive / failed / unknown
    status = _run(["systemctl", "is-active", svc])
    result["status"] = status if status else "unknown"

    # Memory via systemctl MemoryCurrent (cgroup-based, bytes)
    mem_raw = _run(["systemctl", "show", svc, "--property=MemoryCurrent", "--value"])
    if mem_raw and mem_raw.isdigit():
        mem_bytes = int(mem_raw)
        result["memory_bytes"] = mem_bytes
        result["memory_human"] = _human_memory(mem_bytes)

    # Uptime: ActiveEnterTimestamp in microseconds
    active_ts = _run(["systemctl", "show", svc, "--property=ActiveEnterTimestamp", "--value"])
    if active_ts:
        # Parse: "Day YYYY-MM-DD HH:MM:SS TZ"
        try:
            parts = active_ts.split(" ", 1)
            if len(parts) >= 2:
                ts_str = parts[1]  # "2025-06-01 14:30:00 CST"
                ts_str = " ".join(ts_str.split()[:2])  # drop timezone
                started = time.mktime(time.strptime(ts_str, "%Y-%m-%d %H:%M:%S"))
                uptime = time.time() - started
                if uptime >= 0:
                    result["uptime_seconds"] = int(uptime)
                    result["uptime_human"] = _human_duration(uptime)
        except (ValueError, OSError):
            pass

    # Port check
    port = result["port"]
    if port:
        check = _run(["ss", "-tlnp"])
        if f":{port}" in check:
            result["port_active"] = True

    # Creation time: directory birth time (or last modification as fallback)
    path = result["path"]
    if path:
        dir_path = Path(path)
        if dir_path.is_dir():
            try:
                stat = dir_path.stat()
                result["created_at"] = time.strftime(
                    "%Y-%m-%d %H:%M", time.localtime(stat.st_ctime)
                )
            except OSError:
                pass

    return result


class DashboardHandler(BaseHTTPRequestHandler):
    """Single-route handler: / → index.html, /api/projects → JSON."""

    def do_GET(self) -> None:
        if self.path == "/" or self.path == "/index.html":
            self._serve_html()
        elif self.path == "/api/projects":
            self._serve_api()
        elif self.path == "/health":
            self._write_json({"status": "ok"})
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_html(self) -> None:
        body = HTML_FILE.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_api(self) -> None:
        projects = []
        if PROJECTS_FILE.exists():
            try:
                data = json.loads(PROJECTS_FILE.read_text(encoding="utf-8"))
                raw = data.get("projects", [])
            except (json.JSONDecodeError, OSError):
                raw = []
            for proj in raw:
                projects.append(_collect_project(proj))

        self._write_json({"projects": projects, "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")})

    def _write_json(self, payload: dict) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: object) -> None:
        pass  # suppress default stderr logging


def main() -> None:
    server = ThreadingHTTPServer((HOST, PORT), DashboardHandler)
    server.allow_reuse_address = True
    print(f"vps-dashboard listening on {HOST}:{PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down...")
        server.shutdown()


if __name__ == "__main__":
    main()
