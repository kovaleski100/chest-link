"""Semi-automated emulator boot smoke scenarios with isolated profiles."""
import os
from pathlib import Path
import re
import select
import subprocess
import sys
import time

from tests.e2e.artifacts import capture_screenshot
from tests.e2e.config import ROOT, console_build_path


class ScenarioSkipped(Exception):
    pass


def ensure_console_pair(ctx):
    nds = console_build_path("ds")
    threeds = console_build_path("3ds")
    if not ctx.build:
        missing = [str(path) for path in (nds, threeds) if not path.is_file()]
        if missing:
            raise RuntimeError(
                "--no-build foi solicitado, mas faltam builds do par DS/3DS: "
                + ", ".join(missing)
            )
        return
    build = subprocess.run(["make", "-C", str(ROOT), "consoles"], text=True,
                           capture_output=True, timeout=900, check=False)
    log = ctx.artifacts.path / "logs" / "console-build.log"
    log.write_text(build.stdout + build.stderr, encoding="utf-8")
    if build.returncode:
        raise RuntimeError(f"Falha ao compilar o par DS/3DS; veja {log}")
    if not nds.is_file() or not threeds.is_file():
        raise RuntimeError("O comando consoles terminou sem os dois builds esperados.")


def _isolated_env(profile):
    profile = Path(profile)
    env = os.environ.copy()
    env.update({
        "HOME": str(profile / "home"),
        "XDG_CONFIG_HOME": str(profile / "config"),
        "XDG_DATA_HOME": str(profile / "data"),
        "XDG_CACHE_HOME": str(profile / "cache"),
    })
    for key in ("HOME", "XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME"):
        Path(env[key]).mkdir(parents=True, exist_ok=True, mode=0o700)
    return env


def _melonds_config(config_home, dldi_folder):
    config_dir = Path(config_home) / "melonDS"
    config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    config = config_dir / "melonDS.toml"
    quoted = '"' + str(Path(dldi_folder).resolve()).replace("\\", "\\\\").replace('"', '\\"') + '"'
    current = config.read_text(encoding="utf-8") if config.is_file() else ""
    current = re.sub(r"(?ms)^\[DLDI\]\s*.*?(?=^\[|\Z)", "", current).rstrip()
    if not re.search(r"(?m)^\[Emu\]\s*$", current):
        current = (current + "\n\n" if current else "") + "[Emu]\nDirectBoot = true"
    dldi = ("[DLDI]\nEnable = true\nReadOnly = false\nFolderSync = true\n"
            f"FolderPath = {quoted}\n")
    config.write_text(current + "\n\n" + dldi, encoding="utf-8")
    os.chmod(config, 0o600)


def _operator_confirmation(ctx, process, prompt, timeout):
    if not sys.stdin.isatty():
        raise ScenarioSkipped("boot visual exige confirmação interativa; use um terminal")
    print(prompt, flush=True)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"O emulador encerrou com código {process.poll()}.")
        ready, _, _ = select.select([sys.stdin], [], [], 0.2)
        if ready:
            answer = sys.stdin.readline().strip().lower()
            if answer in {"s", "sim", "y", "yes"}:
                return True
            if answer in {"n", "nao", "não", "no"}:
                raise RuntimeError("Operador confirmou que o menu/storage não chegou ao estado esperado.")
            print("Responda s ou n.", flush=True)
    screenshot = capture_screenshot(ctx.environment,
                                    ctx.artifacts.path / "screenshots" / "emulator-timeout.png")
    if screenshot:
        ctx.extra_artifacts.append(str(screenshot))
    raise TimeoutError(f"Confirmação do menu excedeu {timeout}s.")


def start_ds(ctx, *, transfer=False):
    rom = console_build_path("ds")
    run_dir = ctx.artifacts.path / "ds"
    storage = run_dir / "dldi"
    if transfer:
        from tests.e2e.scenarios.common import create_synthetic_bank
        fixture = create_synthetic_bank(storage / "_nds" / "pkmn-chest")
    else:
        fixture = None
        storage.mkdir(parents=True, exist_ok=True, mode=0o700)
    profile = ROOT / "build" / "e2e" / "profiles" / "melonds"
    env = _isolated_env(profile)
    _melonds_config(env["XDG_CONFIG_HOME"], storage)
    emulator = ctx.processes.start("melonDS", [ctx.environment.melon_ds, str(rom)],
                                   run_dir / "melonds.log", cwd=ROOT, env=env)
    return emulator, fixture, rom, profile, storage


def run_ds_boot(ctx):
    if not ctx.environment.melon_ds:
        raise ScenarioSkipped("melonDS não está instalado; defina CHESTLINK_MELONDS")
    if ctx.environment.display_session == "headless":
        raise ScenarioSkipped("melonDS requer uma sessão gráfica para a confirmação visual")
    if not sys.stdin.isatty():
        raise ScenarioSkipped("boot visual exige confirmação interativa; use um terminal")
    ensure_console_pair(ctx)
    run_dir = ctx.artifacts.path / "ds"
    emulator, fixture, rom, profile, _storage = start_ds(ctx, transfer=True)
    prompt = (
        "Confirme no terminal somente quando o Chest Link estiver no menu e a box sintética "
        "e2e estiver visível em Consultar bancos (e2e: s/n): "
    )
    _operator_confirmation(ctx, emulator.process, prompt, ctx.timeout_seconds)
    metrics = {"rom": str(rom), "profile": str(profile), "dldi_folder_sync": True,
               "menu_confirmed_by_operator": True, "storage_fixture_present": fixture is not None}
    return ctx.artifacts.record("ds_boot", "PASS", "EMULATOR", metrics=metrics,
                                artifacts=[str(run_dir / "melonds.log")])


def run_3ds_boot(ctx):
    if not ctx.environment.azahar:
        raise ScenarioSkipped("Azahar não está instalado; defina CHESTLINK_AZAHAR")
    if ctx.environment.display_session == "headless":
        raise ScenarioSkipped("Azahar requer uma sessão gráfica para a confirmação visual")
    if not sys.stdin.isatty():
        raise ScenarioSkipped("boot visual exige confirmação interativa; use um terminal")
    ensure_console_pair(ctx)
    rom = console_build_path("3ds")
    run_dir = ctx.artifacts.path / "3ds"
    profile = ROOT / "build" / "e2e" / "profiles" / "azahar"
    env = _isolated_env(profile)
    sdmc = profile / "sdmc" / "3ds" / "ChestLink" / "E2E" / ctx.artifacts.path.name
    sdmc.mkdir(parents=True, exist_ok=True, mode=0o700)
    argv = [ctx.environment.azahar, str(rom)]
    emulator = ctx.processes.start("Azahar", argv, run_dir / "azahar.log", cwd=ROOT, env=env)
    prompt = (
        "Confirme no terminal somente quando o Chest Link 3DS estiver no menu; "
        "a inicialização do menu também exercita a montagem do SD (e2e: s/n): "
    )
    _operator_confirmation(ctx, emulator.process, prompt, ctx.timeout_seconds)
    return ctx.artifacts.record(
        "3ds_boot", "PASS", "EMULATOR",
        reason="Confirmação visual manual; não é validação em 3DS físico.",
        metrics={"rom": str(rom), "isolated_profile": str(profile), "sdmc": str(sdmc),
                 "menu_confirmed_by_operator": True},
        artifacts=[str(run_dir / "azahar.log")],
    )
