"""Per-run artifact directories and structured results."""
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets


class RunArtifacts:
    SUBDIRS = ("server", "ds", "3ds", "logs", "screenshots", "artifacts", "private")

    def __init__(self, root):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        self.path = Path(root) / f"run-{stamp}-{os.getpid()}-{secrets.token_hex(3)}"
        self.path.mkdir(parents=True, mode=0o700)
        os.chmod(self.path, 0o700)
        for name in self.SUBDIRS:
            (self.path / name).mkdir(mode=0o700)
        self.results = []
        self.started_at = datetime.now(timezone.utc).isoformat()

    def write_private_json(self, relative, value):
        target = self.path / "private" / relative
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        target.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
        os.chmod(target, 0o600)
        return target

    def write_summary(self, command, environment):
        summary = {
            "format": 1,
            "command": command,
            "startedAt": self.started_at,
            "finishedAt": datetime.now(timezone.utc).isoformat(),
            "environment": environment,
            "scenarios": self.results,
        }
        target = self.path / "artifacts" / "result.json"
        target.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                          encoding="utf-8")
        os.chmod(target, 0o600)
        return target

    def record(self, name, status, surface, *, reason=None, metrics=None, artifacts=None):
        row = {"scenario": name, "status": status, "surface": surface}
        if reason:
            row["reason"] = reason
        if metrics:
            row["metrics"] = metrics
        if artifacts:
            row["artifacts"] = artifacts
        self.results.append(row)
        return row


def capture_screenshot(environment, output):
    """Best-effort desktop capture. Returns None when no supported tool exists."""
    if not environment.screenshot_tool:
        return None
    import subprocess

    output = Path(output)
    tool = Path(environment.screenshot_tool).name
    if tool == "scrot":
        argv = [environment.screenshot_tool, str(output)]
    elif tool == "gnome-screenshot":
        argv = [environment.screenshot_tool, f"--file={output}"]
    elif tool == "import":
        argv = [environment.screenshot_tool, "-window", "root", str(output)]
    elif tool == "grim":
        argv = [environment.screenshot_tool, str(output)]
    elif tool == "spectacle":
        argv = [environment.screenshot_tool, "-b", "-n", "-o", str(output)]
    else:
        return None
    try:
        subprocess.run(argv, check=True, timeout=15, stdin=subprocess.DEVNULL,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    return output if output.is_file() else None
