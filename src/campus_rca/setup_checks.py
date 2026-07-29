"""System setup checks shared by the launcher and Tkinter UI."""

from __future__ import annotations

import os
import platform
import shutil
import socket
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from campus_rca.config import ROOT


@dataclass
class CheckItem:
    name: str
    ok: bool
    detail: str
    fix: str = ""


@dataclass
class SetupReport:
    os_name: str
    arch: str
    checks: list[CheckItem] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        required = {"Python", "uv", "Project env", "Tkinter", "Ollama"}
        return all(c.ok for c in self.checks if c.name in required)

    def to_dict(self) -> dict[str, Any]:
        return {
            "os_name": self.os_name,
            "arch": self.arch,
            "ready": self.ready,
            "checks": [asdict(c) for c in self.checks],
        }


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _run(cmd: list[str], timeout: int = 30) -> tuple[int, str]:
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(ROOT),
        )
        out = (p.stdout or "") + (p.stderr or "")
        return p.returncode, out.strip()
    except Exception as exc:  # noqa: BLE001
        return 1, str(exc)


def detect_platform() -> tuple[str, str]:
    os_name = platform.system()
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        arch = "x86_64"
    elif machine in {"aarch64", "arm64"}:
        arch = "arm64"
    else:
        arch = machine
    return os_name, arch


def gather_setup_report() -> SetupReport:
    os_name, arch = detect_platform()
    report = SetupReport(os_name=os_name, arch=arch)

    # Python
    ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    py_ok = sys.version_info[:2] >= (3, 10)
    report.checks.append(
        CheckItem(
            "Python",
            py_ok,
            f"{sys.executable} ({ver})",
            "Install Python 3.10+",
        )
    )

    # Tkinter
    try:
        import tkinter  # noqa: F401

        report.checks.append(CheckItem("Tkinter", True, "import ok"))
    except Exception as exc:  # noqa: BLE001
        fix = "sudo apt install python3-tk" if os_name == "Linux" else "Install python-tk"
        report.checks.append(CheckItem("Tkinter", False, str(exc), fix))

    # uv
    uv = shutil.which("uv")
    report.checks.append(
        CheckItem(
            "uv",
            bool(uv),
            uv or "not found",
            "curl -LsSf https://astral.sh/uv/install.sh | sh",
        )
    )

    # Project env
    venv_py = ROOT / ".venv" / "bin" / "python"
    if os_name == "Windows":
        venv_py = ROOT / ".venv" / "Scripts" / "python.exe"
    env_ok = venv_py.exists()
    report.checks.append(
        CheckItem(
            "Project env",
            env_ok,
            str(venv_py) if env_ok else ".venv missing",
            "uv sync",
        )
    )

    # .env
    env_file = ROOT / ".env"
    report.checks.append(
        CheckItem(
            ".env",
            env_file.exists(),
            str(env_file) if env_file.exists() else "missing",
            "cp .env.example .env",
        )
    )

    # Ollama
    ollama_bin = shutil.which("ollama")
    ollama_up = _port_open("127.0.0.1", 11434)
    model = os.environ.get("OLLAMA_MODEL", "")
    if not model and env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("OLLAMA_MODEL="):
                model = line.split("=", 1)[1].strip().strip("'\"")
                break
    model = model or "llama3.2:3b"
    detail = (
        f"cli={'yes' if ollama_bin else 'no'}, api={'up' if ollama_up else 'down'}, "
        f"preferred={model or '?'}, local=[{', '.join(list_ollama_models()[:5])}]"
    )
    report.checks.append(
        CheckItem(
            "Ollama",
            bool(ollama_bin and ollama_up),
            detail,
            "Install Ollama, run: ollama serve && ollama pull " + model,
        )
    )

    # Batfish / Docker / Podman
    docker = shutil.which("docker")
    podman = shutil.which("podman")
    bf = _port_open("127.0.0.1", 9996) or _port_open("127.0.0.1", 9997)
    uid = os.getuid() if hasattr(os, "getuid") else 0
    sock = Path(f"/run/user/{uid}/podman/podman.sock")
    detail = (
        f"docker={'yes' if docker else 'no'}, podman={'yes' if podman else 'no'}, "
        f"podman_sock={'yes' if sock.exists() else 'no'}, service={'up' if bf else 'down'}"
    )
    report.checks.append(
        CheckItem(
            "Batfish",
            bf,
            detail,
            "Click Start Batfish in GUI, or: systemctl --user enable --now podman.socket && ./scripts/ensure_batfish.sh",
        )
    )

    return report


def ensure_project_synced() -> tuple[bool, str]:
    if not shutil.which("uv"):
        return False, "uv not installed"
    code, out = _run(["uv", "sync", "--python", sys.executable], timeout=600)
    return code == 0, out or "uv sync ok"


def start_ollama_serve() -> tuple[bool, str]:
    if _port_open("127.0.0.1", 11434):
        return True, "already running"
    if not shutil.which("ollama"):
        return False, "ollama not installed"
    subprocess.Popen(
        ["ollama", "serve"],
        stdout=open("/tmp/campus-rca-ollama.log", "a", encoding="utf-8"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    import time

    for _ in range(30):
        if _port_open("127.0.0.1", 11434):
            return True, "started"
        time.sleep(1)
    return False, "timeout waiting for ollama"


def list_ollama_models(base_url: str = "http://localhost:11434") -> list[str]:
    """Return locally installed Ollama model names (never pulls)."""
    names: list[str] = []
    # Prefer CLI (works even if API format differs)
    if shutil.which("ollama"):
        code, out = _run(["ollama", "list"], timeout=30)
        if code == 0 and out:
            for line in out.splitlines()[1:]:
                parts = line.split()
                if parts:
                    names.append(parts[0])
    if names:
        return names
    # Fallback: HTTP tags API
    try:
        import json
        import urllib.request

        with urllib.request.urlopen(f"{base_url.rstrip('/')}/api/tags", timeout=5) as resp:
            data = json.loads(resp.read().decode())
        for m in data.get("models") or []:
            name = m.get("name") or m.get("model")
            if name:
                names.append(name)
    except Exception:  # noqa: BLE001
        pass
    return names


def model_is_local(model: str, local_models: list[str] | None = None) -> bool:
    """True if model is already on disk (exact or tag/family match)."""
    return resolve_local_model_name(model, local_models) is not None


def resolve_local_model_name(model: str, local_models: list[str] | None = None) -> str | None:
    """Return the concrete local tag to use for `model`, or None if missing."""
    models = local_models if local_models is not None else list_ollama_models()
    model = model.strip()
    for m in models:
        if m == model:
            return m
    for m in models:
        if m.startswith(model + ":"):
            return m
    if ":" not in model:
        for m in models:
            if m.split(":")[0] == model:
                return m
    return None


def set_env_ollama_model(model: str, env_path: Path | None = None) -> None:
    path = env_path or (ROOT / ".env")
    model = model.strip()
    if not path.exists():
        path.write_text(f"OLLAMA_MODEL={model}\n", encoding="utf-8")
        return
    lines = path.read_text(encoding="utf-8").splitlines()
    found = False
    out: list[str] = []
    for line in lines:
        if line.startswith("OLLAMA_MODEL="):
            out.append(f"OLLAMA_MODEL={model}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"OLLAMA_MODEL={model}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def pull_ollama_model(model: str, *, force: bool = False) -> tuple[bool, str]:
    """Pull only if missing locally (unless force=True)."""
    if not shutil.which("ollama"):
        return False, "ollama not installed"
    local = list_ollama_models()
    concrete = resolve_local_model_name(model, local)
    if concrete and not force:
        return True, f"already local — skipped download ({concrete})"
    code, out = _run(["ollama", "pull", model], timeout=3600)
    return code == 0, out[-2000:] if out else "ok"
