"""
vps-dashboard server — lightweight project dashboard for VPS.
Listens on 127.0.0.1:9090 only. Reverse-proxied by Nginx.
"""
import json
import os
import subprocess
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
try:
    from http.server import ThreadingHTTPServer  # Python 3.7+
except ImportError:  # pragma: no cover - Python 3.6 fallback
    from http.server import HTTPServer
    from socketserver import ThreadingMixIn

    class ThreadingHTTPServer(ThreadingMixIn, HTTPServer):
        daemon_threads = True
from pathlib import Path

HOST = "127.0.0.1"
PORT = 9090
PROJECTS_FILE = Path(__file__).resolve().parent / "projects.json"
SERVERS_FILE = Path(__file__).resolve().parent / "servers.json"
HTML_FILE = Path(__file__).resolve().parent / "index.html"
CACHE_SECONDS = 5

_pid_cache = {}
_remote_cache = {}
REMOTE_CACHE_SECONDS = 60

try:
    import paramiko  # type: ignore
except ImportError:
    paramiko = None  # remote server collection disabled

# One-shot remote collection script (KEY=VALUE lines, easy to parse)
REMOTE_COLLECT_CMD = (
    'echo "HOSTNAME=$(hostname)";'
    'echo "LOAD=$(cat /proc/loadavg)";'
    'echo "MEM=$(free -b | awk \'/^Mem:/{print $2,$3}\')";'
    'echo "DISK=$(df -B1 / | awk \'NR==2{print $2,$3}\')";'
    'echo "UPTIME=$(cat /proc/uptime | awk \'{print $1}\')";'
    'echo "CORES=$(nproc)";'
    'echo "KERNEL=$(uname -r)";'
    'echo "OS=$(grep -m1 PRETTY_NAME /etc/os-release | cut -d= -f2- | tr -d \'"\')"'
)

# Remote project collector: a python script piped via stdin.
# Reads the project list as JSON, queries systemd/docker/ports, prints results as JSON.
REMOTE_PROJECT_SCRIPT = r'''
import json, subprocess, sys, time, os, datetime, re
projects = json.loads(sys.stdin.read())
def run(cmd):
    try:
        r = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE,
                           stderr=subprocess.PIPE, universal_newlines=True, timeout=12)
        return r.stdout.strip()
    except Exception:
        return ""
def parse_uptime(s):
    if not s:
        return None
    s = s.strip()
    try:
        if "T" in s:
            s2 = s.replace("Z", "").split(".")[0]
            dt = datetime.datetime.strptime(s2, "%Y-%m-%dT%H:%M:%S")
            now = datetime.datetime.utcnow()
            return max(0, int((now - dt).total_seconds()))
        parts = s.split()
        if len(parts) >= 3:
            t = time.mktime(time.strptime(parts[1] + " " + parts[2], "%Y-%m-%d %H:%M:%S"))
            return max(0, int(time.time() - t))
    except Exception:
        pass
    return None
def mem_to_bytes(s):
    try:
        part = s.split("/")[0].strip()
        m = re.match(r"([\d.]+)\s*([A-Za-z]+)", part)
        if not m:
            return None
        num = float(m.group(1))
        unit = m.group(2)
        table = {"KiB": 1024, "MiB": 1024**2, "GiB": 1024**3, "TiB": 1024**4,
                 "kB": 1000, "MB": 1000**2, "GB": 1000**3, "B": 1}
        return int(num * table.get(unit, 1))
    except Exception:
        return None
out = []
for p in projects:
    res = {"status": "unknown", "memory_bytes": None, "uptime_seconds": None,
           "port_active": False, "created_at": None}
    t = p.get("type", "systemd")
    svc = p.get("service_name")
    if t == "systemd" and svc:
        st = run("systemctl is-active " + svc)
        res["status"] = st if st else "unknown"
        mem = run("systemctl show %s --property=MemoryCurrent --value" % svc)
        if mem.isdigit():
            res["memory_bytes"] = int(mem)
        res["uptime_seconds"] = parse_uptime(
            run("systemctl show %s --property=ActiveEnterTimestamp --value" % svc))
    elif t == "docker" and svc:
        st = run("docker inspect --format '{{.State.Status}}' " + svc)
        res["status"] = st if st else "unknown"
        mem = run("docker stats --no-stream --format '{{.MemUsage}}' " + svc)
        res["memory_bytes"] = mem_to_bytes(mem)
        res["uptime_seconds"] = parse_uptime(
            run("docker inspect --format '{{.State.StartedAt}}' " + svc))
    port = p.get("port")
    if port:
        res["port_active"] = (":" + str(port)) in run("ss -tln")
    if t == "port":
        res["status"] = "active" if res["port_active"] else "inactive"
    path = p.get("path")
    if path and os.path.isdir(path):
        try:
            res["created_at"] = time.strftime(
                "%Y-%m-%d %H:%M", time.localtime(os.stat(path).st_ctime))
        except OSError:
            pass
    out.append(res)
print(json.dumps(out, ensure_ascii=False))
'''


def _run(cmd, timeout = 5.0):
    """Run a shell command, return stripped stdout or empty string on failure."""
    try:
        result = subprocess.run(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            universal_newlines=True, timeout=timeout)
        return result.stdout.strip()
    except Exception:
        return ""


def _human_duration(seconds):
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


def _human_memory(bytes_val):
    """Convert bytes to human-readable memory string."""
    if bytes_val <= 0:
        return "N/A"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if abs(bytes_val) < 1024.0:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024.0
    return f"{bytes_val:.1f} PB"


def _mem_to_bytes(s):
    """Parse '70.26MiB / 1.843GiB' (docker stats MemUsage) into bytes."""
    try:
        part = s.split("/")[0].strip()
        num_s, _, unit = part.partition(" ")
        if not unit:
            import re

            m = re.match(r"([\d.]+)\s*([A-Za-z]+)", part)
            if not m:
                return None
            num_s, unit = m.group(1), m.group(2)
        num = float(num_s)
        table = {"KiB": 1024, "MiB": 1024**2, "GiB": 1024**3, "TiB": 1024**4,
                 "kB": 1000, "MB": 1000**2, "GB": 1000**3, "B": 1}
        return int(num * table.get(unit, 1))
    except Exception:
        return None


def _parse_started_at(s):
    """Parse '2026-07-29T08:12:34.567890123Z' (docker StartedAt) into uptime seconds."""
    if not s:
        return None
    try:
        s2 = s.replace("Z", "").split(".")[0]
        dt = time.strptime(s2, "%Y-%m-%dT%H:%M:%S")
        started = time.mktime(dt)
        return max(0, int(time.time() - started))
    except (ValueError, OSError):
        return None


def _get_pid(service_name):
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


def _collect_project(proj):
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
    ptype = proj.get("type", "systemd")
    if ptype == "docker" and svc:
        # Docker container
        status = _run(["docker", "inspect", "--format", "{{.State.Status}}", svc])
        result["status"] = status if status else "unknown"
        mem = _run(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", svc])
        mem_b = _mem_to_bytes(mem)
        if mem_b:
            result["memory_bytes"] = mem_b
            result["memory_human"] = _human_memory(mem_b)
        started = _run(["docker", "inspect", "--format", "{{.State.StartedAt}}", svc])
        up = _parse_started_at(started)
        if up:
            result["uptime_seconds"] = up
            result["uptime_human"] = _human_duration(up)
    elif ptype == "port":
        # Port-based health (PM2 / uvicorn etc.)
        port = result["port"]
        if port:
            check = _run(["ss", "-tlnp"])
            result["port_active"] = f":{port}" in check
        result["status"] = "active" if result["port_active"] else "inactive"
    elif not svc:
        return result
    else:
        # systemd service (default)
        status = _run(["systemctl", "is-active", svc])
        result["status"] = status if status else "unknown"

        # Memory via systemctl MemoryCurrent (cgroup-based, bytes)
        mem_raw = _run(["systemctl", "show", svc, "--property=MemoryCurrent", "--value"])
        if mem_raw and mem_raw.isdigit():
            mem_bytes = int(mem_raw)
            result["memory_bytes"] = mem_bytes
            result["memory_human"] = _human_memory(mem_bytes)

        # Uptime
        active_ts = _run(["systemctl", "show", svc, "--property=ActiveEnterTimestamp", "--value"])
        if active_ts:
            try:
                parts = active_ts.split(" ", 1)
                if len(parts) >= 2:
                    ts_str = parts[1]
                    ts_str = " ".join(ts_str.split()[:2])
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

    # Creation time
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


def _collect_server_info():
    """Collect host-level server info."""
    info = {
        "hostname": os.uname().nodename if hasattr(os, "uname") else "unknown",
        "kernel": "",
        "os": "",
        "cpu_model": "",
        "cpu_cores": 0,
        "load_1m": None,
        "load_5m": None,
        "load_15m": None,
        "ram_total_human": "N/A",
        "ram_used_human": "N/A",
        "ram_total_bytes": None,
        "ram_used_bytes": None,
        "ram_percent": None,
        "disk_total_human": "N/A",
        "disk_used_human": "N/A",
        "disk_percent": None,
        "uptime_seconds": None,
        "uptime_human": "N/A",
    }

    # CPU info
    cpu = _run(["lscpu"])
    for line in cpu.split(chr(10)):
        if "Model name" in line:
            info["cpu_model"] = line.split(":", 1)[1].strip()
        if "CPU(s)" in line and "NUMA" not in line and "On-line" not in line:
            try:
                info["cpu_cores"] = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass

    # Kernel
    info["kernel"] = _run(["uname", "-r"])

    # OS pretty name
    info["os"] = _run(["sh", "-c", "grep -m1 PRETTY_NAME /etc/os-release | cut -d= -f2- | tr -d '\"'"])

    # Load
    load = _run(["cat", "/proc/loadavg"])
    if load:
        parts = load.split()
        if len(parts) >= 3:
            try:
                info["load_1m"] = float(parts[0])
                info["load_5m"] = float(parts[1])
                info["load_15m"] = float(parts[2])
            except ValueError:
                pass

    # RAM
    mem = _run(["free", "-b"])
    if mem:
        for line in mem.split(chr(10)):
            if "Mem:" in line:
                fields = line.split()
                if len(fields) >= 3:
                    try:
                        total = int(fields[1])
                        used = int(fields[2])
                        info["ram_total_bytes"] = total
                        info["ram_used_bytes"] = used
                        info["ram_total_human"] = _human_memory(total)
                        info["ram_used_human"] = _human_memory(used)
                        if total > 0:
                            info["ram_percent"] = round(used / total * 100, 1)
                    except (ValueError, IndexError):
                        pass
                break

    # Disk
    disk = _run(["df", "-B1", "/"])
    if disk:
        for line in disk.split(chr(10)):
            fields = line.split()
            if len(fields) >= 4 and fields[0].startswith("/"):
                try:
                    total_d = int(fields[1])
                    used_d = int(fields[2])
                    info["disk_total_human"] = _human_memory(total_d)
                    info["disk_used_human"] = _human_memory(used_d)
                    if total_d > 0:
                        info["disk_percent"] = round(used_d / total_d * 100, 1)
                except (ValueError, IndexError):
                    pass
                break

    # System uptime
    uptime_raw = _run(["cat", "/proc/uptime"])
    if uptime_raw:
        try:
            up_sec = float(uptime_raw.split()[0])
            info["uptime_seconds"] = int(up_sec)
            info["uptime_human"] = _human_duration(up_sec)
        except (ValueError, IndexError):
            pass

    return info


def _collect_remote_server(cfg):
    """Collect metrics from a remote server over SSH (paramiko), cached 60s."""
    host = cfg.get("host", "")
    now = time.time()
    cached = _remote_cache.get(host)
    if cached and (now - cached[0]) < REMOTE_CACHE_SECONDS:
        return cached[1]
    result = _collect_remote_now(cfg)
    _remote_cache[host] = (now, result)
    return result


def _collect_remote_now(cfg):
    """Collect metrics from a remote server over SSH (paramiko)."""
    result = {
        "name": cfg.get("name", ""),
        "host": cfg.get("host", ""),
        "port": cfg.get("port", 22),
        "plan": cfg.get("plan") or None,
        "note": cfg.get("note") or None,
        "local": bool(cfg.get("local")),
        "status": "offline",
        "hostname": None,
        "os": None,
        "kernel": None,
        "cpu_cores": None,
        "load_1m": None,
        "load_5m": None,
        "load_15m": None,
        "ram_total_human": None,
        "ram_used_human": None,
        "ram_percent": None,
        "disk_total_human": None,
        "disk_used_human": None,
        "disk_percent": None,
        "uptime_human": None,
        "error": None,
    }

    if paramiko is None:
        result["error"] = "paramiko 未安装，无法采集远程服务器"
        return result

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            hostname=cfg["host"],
            port=int(cfg.get("port", 22)),
            username=cfg.get("user", "root"),
            password=cfg.get("password", ""),
            timeout=8,
            banner_timeout=8,
            auth_timeout=8,
            look_for_keys=False,
            allow_agent=False,
        )
        _stdin, stdout, _stderr = client.exec_command(REMOTE_COLLECT_CMD, timeout=15)
        out = stdout.read().decode("utf-8", errors="replace")
        client.close()
    except Exception as exc:  # noqa: BLE001 - network failures come in many shapes
        result["error"] = str(exc)[:120]
        return result

    kv = {}
    for line in out.splitlines():
        line = line.strip()
        if "=" in line:
            key, _, val = line.partition("=")
            kv[key.strip()] = val.strip()

    result["status"] = "online"
    result["hostname"] = kv.get("HOSTNAME") or None

    os_str = kv.get("OS")
    if os_str:
        result["os"] = os_str.strip('"')

    result["kernel"] = kv.get("KERNEL") or None

    cores = kv.get("CORES")
    if cores and cores.isdigit():
        result["cpu_cores"] = int(cores)

    load = kv.get("LOAD")
    if load:
        parts = load.split()
        if len(parts) >= 3:
            try:
                result["load_1m"] = float(parts[0])
                result["load_5m"] = float(parts[1])
                result["load_15m"] = float(parts[2])
            except ValueError:
                pass

    mem = kv.get("MEM")
    if mem:
        fields = mem.split()
        if len(fields) >= 2:
            try:
                total_b = int(fields[0])
                used_b = int(fields[1])
                result["ram_total_human"] = _human_memory(total_b)
                result["ram_used_human"] = _human_memory(used_b)
                if total_b > 0:
                    result["ram_percent"] = round(used_b / total_b * 100, 1)
            except ValueError:
                pass

    disk = kv.get("DISK")
    if disk:
        fields = disk.split()
        if len(fields) >= 2:
            try:
                total_d = int(fields[0])
                used_d = int(fields[1])
                result["disk_total_human"] = _human_memory(total_d)
                result["disk_used_human"] = _human_memory(used_d)
                if total_d > 0:
                    result["disk_percent"] = round(used_d / total_d * 100, 1)
            except ValueError:
                pass

    uptime_raw = kv.get("UPTIME")
    if uptime_raw:
        try:
            up_sec = float(uptime_raw)
            if up_sec >= 0:
                result["uptime_human"] = _human_duration(int(up_sec))
        except ValueError:
            pass

    return result


def _remote_project_cmd():
    """Build a one-liner that runs REMOTE_PROJECT_SCRIPT on a (possibly py3.6) remote.
    Script travels base64-encoded via -c; project data flows through stdin."""
    import base64

    b64 = base64.b64encode(REMOTE_PROJECT_SCRIPT.encode("utf-8")).decode("ascii")
    return "python3 -c \"import base64,sys;exec(base64.b64decode('" + b64 + "').decode())\""


def _collect_remote_projects(server_cfg, projects):
    """Collect project metrics on a remote server in one SSH round-trip (cached 60s)."""
    key = server_cfg.get("host", "")
    now = time.time()
    cached = _remote_cache.get("proj:" + key)
    if cached and (now - cached[0]) < REMOTE_CACHE_SECONDS:
        return cached[1]

    empty = []
    for p in projects:
        r = _collect_project(p)  # local fallback shape (will fail gracefully remotely)
        r["server"] = p.get("server")
        r["type"] = p.get("type", "systemd")
        empty.append(r)

    if paramiko is None:
        for r in empty:
            r["status"] = "unknown"
            r["error"] = "paramiko 未安装，无法采集远程项目"
        _remote_cache["proj:" + key] = (now, empty)
        return empty

    results = list(empty)
    try:
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            hostname=server_cfg.get("host", ""),
            port=int(server_cfg.get("port", 22)),
            username=server_cfg.get("user", "root"),
            password=server_cfg.get("password", ""),
            timeout=8,
            banner_timeout=8,
            auth_timeout=8,
            look_for_keys=False,
            allow_agent=False,
        )
        stdin, stdout, _stderr = client.exec_command(_remote_project_cmd(), timeout=25)
        stdin.write(json.dumps(projects, ensure_ascii=False))
        stdin.flush()
        stdin.channel.shutdown_write()
        out = stdout.read().decode("utf-8", errors="replace")
        client.close()
        data = json.loads(out)
        for i, r in enumerate(results):
            if i < len(data):
                r.update({k: v for k, v in data[i].items() if v is not None})
                r["error"] = None
                # Recompute human-readable fields after merging remote values
                if r.get("memory_bytes") and not r.get("memory_human"):
                    r["memory_human"] = _human_memory(r["memory_bytes"])
                if r.get("uptime_seconds") and not r.get("uptime_human"):
                    r["uptime_human"] = _human_duration(r["uptime_seconds"])
    except Exception as exc:  # noqa: BLE001
        for r in results:
            r["status"] = "offline"
            r["error"] = str(exc)[:120]

    _remote_cache["proj:" + key] = (now, results)
    return results


def _collect_all_servers():
    """Collect all servers from servers.json: local directly, remote over SSH."""
    servers = []
    if not SERVERS_FILE.exists():
        return servers
    try:
        data = json.loads(SERVERS_FILE.read_text(encoding="utf-8"))
        raw = data.get("servers", [])
    except (json.JSONDecodeError, OSError):
        raw = []
    for cfg in raw:
        if cfg.get("local"):
            info = _collect_server_info()
            servers.append(
                {
                    "name": cfg.get("name", "本机"),
                    "host": cfg.get("host", ""),
                    "port": cfg.get("port", 22),
                    "plan": cfg.get("plan") or None,
                    "note": cfg.get("note") or None,
                    "local": True,
                    "status": "online",
                    "hostname": info["hostname"],
                    "os": info["os"],
                    "kernel": info["kernel"],
                    "cpu_cores": info["cpu_cores"],
                    "load_1m": info["load_1m"],
                    "load_5m": info["load_5m"],
                    "load_15m": info["load_15m"],
                    "ram_total_human": info["ram_total_human"],
                    "ram_used_human": info["ram_used_human"],
                    "ram_percent": info["ram_percent"],
                    "disk_total_human": info["disk_total_human"],
                    "disk_used_human": info["disk_used_human"],
                    "disk_percent": info["disk_percent"],
                    "uptime_human": info["uptime_human"],
                    "error": None,
                }
            )
        else:
            servers.append(_collect_remote_server(cfg))
    return servers


class DashboardHandler(BaseHTTPRequestHandler):
    """Single-route handler: / → index.html, /api/projects → JSON, /api/server → JSON."""

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            self._serve_html()
        elif self.path == "/api/projects":
            self._serve_projects()
        elif self.path == "/api/server":
            self._serve_server()
        elif self.path == "/api/servers":
            self._serve_servers()
        elif self.path == "/health":
            self._write_json({"status": "ok"})
        else:
            self.send_response(404)
            self.end_headers()

    def _serve_html(self):
        body = HTML_FILE.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _serve_projects(self):
        raw = []
        if PROJECTS_FILE.exists():
            try:
                data = json.loads(PROJECTS_FILE.read_text(encoding="utf-8"))
                raw = data.get("projects", [])
            except (json.JSONDecodeError, OSError):
                raw = []

        projects = []
        # Local projects (no "server" key) -> collect on this host
        for proj in raw:
            if not proj.get("server"):
                projects.append(_collect_project(proj))

        # Remote projects -> group by server name, one SSH round-trip per server
        remote_groups = {}
        for proj in raw:
            if proj.get("server"):
                remote_groups.setdefault(str(proj["server"]), []).append(proj)

        if remote_groups:
            servers_cfg = {}
            if SERVERS_FILE.exists():
                try:
                    servers_cfg = {
                        str(cfg.get("name")): cfg
                        for cfg in json.loads(SERVERS_FILE.read_text(encoding="utf-8")).get("servers", [])
                    }
                except (json.JSONDecodeError, OSError):
                    servers_cfg = {}
            for srv_name, projs in remote_groups.items():
                cfg = servers_cfg.get(srv_name)
                if not cfg:
                    for p in projs:
                        projects.append(_collect_project(p))
                else:
                    projects.extend(_collect_remote_projects(cfg, projs))

        self._write_json({"projects": projects, "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")})

    def _serve_server(self):
        self._write_json(_collect_server_info())

    def _serve_servers(self):
        self._write_json(
            {"servers": _collect_all_servers(), "updated_at": time.strftime("%Y-%m-%d %H:%M:%S")}
        )

    def _write_json(self, payload):
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        pass  # suppress default stderr logging


def main():
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