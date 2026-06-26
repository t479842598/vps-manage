"""Tests for vps-dashboard server."""
import json
import sys
from pathlib import Path

# Allow running from project root
sys.path.insert(0, str(Path(__file__).resolve().parent))

import server as srv


def test_projects_json_structure(tmp_path, monkeypatch):
    """Verify /api/projects returns correct structure with valid projects.json."""
    # Point PROJECTS_FILE to a temp file
    proj_file = tmp_path / "projects.json"
    monkeypatch.setattr(srv, "PROJECTS_FILE", proj_file)

    proj_file.write_text(
        json.dumps(
            {
                "projects": [
                    {
                        "name": "test-project",
                        "path": "/opt/test",
                        "port": 3000,
                        "description": "A test project",
                        "github_url": "https://github.com/user/repo",
                        "service_name": "test-svc",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # Monkeypatch _run to return canned values
    calls = {}

    def fake_run(cmd, timeout=5.0):
        key = " ".join(cmd)
        calls[key] = calls.get(key, 0) + 1
        if "is-active" in key:
            return "active"
        if "MemoryCurrent" in key:
            return "52428800"  # 50 MB
        if "ActiveEnterTimestamp" in key:
            return "Mon 2025-06-01 14:30:00 CST"
        if "ss" in key:
            return "LISTEN 0 0 0.0.0.0:3000"
        return ""

    monkeypatch.setattr(srv, "_run", fake_run)

    data = json.loads(proj_file.read_text(encoding="utf-8"))
    proj = srv._collect_project(data["projects"][0])

    assert proj["name"] == "test-project"
    assert proj["port"] == 3000
    assert proj["status"] == "active"
    assert proj["memory_bytes"] == 52428800
    assert proj["memory_human"] == "50.0 MB"
    assert proj["port_active"] is True
    assert proj["github_url"] == "https://github.com/user/repo"


def test_missing_optional_fields(monkeypatch):
    """Verify projects.json with minimal fields doesn't crash."""
    proj = srv._collect_project(
        {"name": "minimal", "port": 8080}
    )

    assert proj["name"] == "minimal"
    assert proj["port"] == 8080
    assert proj["github_url"] is None
    assert proj["service_name"] is None
    assert proj["status"] == "unknown"
    assert proj["memory_human"] is None


def test_shell_failure_degrades_gracefully(monkeypatch):
    """Verify that when shell commands fail, fields stay null instead of crashing."""

    def fake_run_fail(cmd, timeout=5.0):
        return ""  # simulate shell command failure returning empty

    monkeypatch.setattr(srv, "_run", fake_run_fail)

    proj = srv._collect_project(
        {"name": "fragile", "port": 9999, "service_name": "fragile-svc"}
    )

    assert proj["name"] == "fragile"
    assert proj["status"] == "unknown"
    assert proj["memory_human"] is None
    assert proj["uptime_human"] is None


def test_human_duration():
    assert "分钟" in srv._human_duration(300)
    assert "小时" in srv._human_duration(7200)
    assert "天" in srv._human_duration(90000)


def test_human_memory():
    assert "KB" in srv._human_memory(2048)
    assert "MB" in srv._human_memory(10485760)
    assert srv._human_memory(0) == "N/A"
    assert srv._human_memory(-1) == "N/A"


def test_host_is_localhost(monkeypatch):
    """Ensure the server binds to 127.0.0.1, not 0.0.0.0."""
    # The HOST constant must be 127.0.0.1
    assert srv.HOST == "127.0.0.1"
    assert srv.PORT == 9090
