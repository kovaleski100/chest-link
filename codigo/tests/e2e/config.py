"""Environment detection and paths for the local E2E lab."""
from dataclasses import dataclass
import os
from pathlib import Path
import shutil
import sys
from typing import Optional


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_ARTIFACT_ROOT = ROOT / "build" / "e2e"


def _configured_program(variable, candidates):
    value = os.environ.get(variable, "").strip()
    if value:
        path = Path(value).expanduser()
        if path.is_file() and os.access(path, os.X_OK):
            return str(path.resolve())
        found = shutil.which(value)
        return str(Path(found).resolve()) if found else None
    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return str(Path(found).resolve())
    return None


@dataclass(frozen=True)
class Environment:
    platform: str
    display_session: str
    melon_ds: Optional[str]
    azahar: Optional[str]
    screenshot_tool: Optional[str]
    input_tool: Optional[str]
    python: str

    @classmethod
    def detect(cls):
        if sys.platform.startswith("linux"):
            platform = "linux"
        elif sys.platform == "darwin":
            platform = "macos"
        elif os.name == "nt":
            platform = "windows"
        else:
            platform = sys.platform
        if os.environ.get("WAYLAND_DISPLAY"):
            display = "wayland"
        elif os.environ.get("DISPLAY"):
            display = "x11"
        else:
            display = "headless"
        return cls(
            platform=platform,
            display_session=display,
            melon_ds=_configured_program("CHESTLINK_MELONDS", ("melonDS", "melonds")),
            azahar=_configured_program("CHESTLINK_AZAHAR", ("azahar", "Azahar")),
            screenshot_tool=next((shutil.which(name) for name in
                                  ("scrot", "gnome-screenshot", "import", "grim", "spectacle")
                                  if shutil.which(name)), None),
            input_tool=next((shutil.which(name) for name in ("xdotool", "ydotool", "wtype")
                             if shutil.which(name)), None),
            python=sys.executable,
        )


def artifact_root():
    configured = os.environ.get("CHESTLINK_E2E_ARTIFACTS")
    return Path(configured).expanduser().resolve() if configured else DEFAULT_ARTIFACT_ROOT


def console_build_path(console):
    if console == "ds":
        return ROOT / "platform" / "nds" / "ChestLink_DS.nds"
    if console == "3ds":
        return ROOT / "platform" / "3ds" / "ChestLink_3DS.3dsx"
    raise ValueError(f"Console desconhecido: {console}")
