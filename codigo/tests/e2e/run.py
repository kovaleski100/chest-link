#!/usr/bin/env python3
"""Run isolated Chest Link host, protocol, emulator, and private-save E2E scenarios."""
import argparse
import os
from pathlib import Path
import subprocess
import sys
import traceback
import signal

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.e2e.artifacts import RunArtifacts, capture_screenshot
from tests.e2e.config import Environment, artifact_root
from tests.e2e.process import ProcessRegistry
from tests.e2e.scenarios.emulator_boot import ScenarioSkipped, run_3ds_boot, run_ds_boot
from tests.e2e.scenarios.ds_to_pc import run as run_ds_to_pc
from tests.e2e.scenarios.hgss import run_console_read, run_cross_platform, run_pc
from tests.e2e.scenarios.protocol_ds_to_pc import run as run_protocol_ds_to_pc
from tests.e2e.scenarios.server_boot import run as run_server_boot


SCENARIOS = {
    "server_boot": run_server_boot,
    "protocol_ds_to_pc": run_protocol_ds_to_pc,
    "ds_boot": run_ds_boot,
    "3ds_boot": run_3ds_boot,
    "ds_to_pc": run_ds_to_pc,
    "hgss_pc_read": run_pc,
    "hgss_ds_read": lambda ctx: run_console_read(ctx, "ds"),
    "hgss_3ds_read": lambda ctx: run_console_read(ctx, "3ds"),
    "hgss_cross_platform_compare": run_cross_platform,
}


class RunContext:
    def __init__(self, artifacts, environment, timeout_seconds, build):
        def terminate(_signal, _frame):
            raise KeyboardInterrupt("E2E process terminated")
        signal.signal(signal.SIGTERM, terminate)
        self.artifacts = artifacts
        self.environment = environment
        self.timeout_seconds = timeout_seconds
        self.build = build
        self.processes = ProcessRegistry()
        self.server = None
        self.extra_artifacts = []
        self.scenario_name = "runner"

    @staticmethod
    def child_env():
        return os.environ.copy()


def _scenario(ctx, name):
    print(f"RUN {name}", flush=True)
    ctx.processes = ProcessRegistry()
    ctx.scenario_name = name
    try:
        result = SCENARIOS[name](ctx)
        if result["status"] == "PASS":
            print(f"PASS {name}", flush=True)
        return result
    except ScenarioSkipped as exc:
        print(f"SKIP {name}: {exc}", flush=True)
        return ctx.artifacts.record(name, "SKIP", "UNAVAILABLE", reason=str(exc))
    except KeyboardInterrupt:
        raise
    except Exception as exc:
        log = ctx.artifacts.path / "logs" / f"{name}-traceback.log"
        log.write_text(traceback.format_exc(), encoding="utf-8")
        screenshot = capture_screenshot(
            ctx.environment, ctx.artifacts.path / "screenshots" / f"{name}-failure.png")
        artifacts = [str(log)]
        if screenshot:
            artifacts.append(str(screenshot))
        artifacts.extend(ctx.extra_artifacts)
        print(f"FAIL {name}: {type(exc).__name__}: {exc}", flush=True)
        print(f"  log: {log}", flush=True)
        return ctx.artifacts.record(name, "FAIL", "LOCAL", reason=f"{type(exc).__name__}: {exc}",
                                    artifacts=artifacts)
    finally:
        try:
            ctx.processes.stop_all()
        except Exception as exc:
            print(f"FAIL process cleanup: {exc}", flush=True)
            ctx.artifacts.record("process_cleanup", "FAIL", "HOST", reason=str(exc))


def _run_command(ctx, name, argv, timeout):
    log = ctx.artifacts.path / "logs" / f"{name}.log"
    print("RUN " + " ".join(argv), flush=True)
    result = subprocess.run(argv, cwd=ROOT, text=True, capture_output=True,
                            timeout=timeout, check=False)
    log.write_text(result.stdout + result.stderr, encoding="utf-8")
    status = "PASS" if result.returncode == 0 else "FAIL"
    print(f"{status} {name}" + (f" (log: {log})" if status == "FAIL" else ""), flush=True)
    ctx.artifacts.record(name, status, "HOST", metrics={"exit_code": result.returncode},
                         artifacts=[str(log)])
    return result.returncode == 0


def _all(ctx, emulator_mode):
    commands_ok = True
    if ctx.build:
        commands_ok &= _run_command(ctx, "console_pair_build", ["make", "-C", str(ROOT), "consoles"], 900)
    if commands_ok:
        commands_ok &= _run_command(
            ctx, "existing_host_suite",
            ["make", "-C", str(ROOT), "console-ports-test", "test", "mailbox-test", "gui-test"],
            900,
        )
    if commands_ok:
        commands_ok &= _run_command(ctx, "e2e_harness_tests",
                                    [sys.executable, "-m", "unittest", "discover", "-s",
                                     "tests/e2e", "-p", "test_*.py", "-v"], 120)
    if not commands_ok:
        return False

    _scenario(ctx, "server_boot")
    _scenario(ctx, "protocol_ds_to_pc")
    _scenario(ctx, "hgss_cross_platform_compare")

    interactive = sys.stdin.isatty() and ctx.environment.display_session != "headless"
    if emulator_mode == "required" or (emulator_mode == "auto" and interactive):
        if ctx.environment.melon_ds:
            _scenario(ctx, "ds_to_pc")
        else:
            reason = "melonDS ausente; instale/configure CHESTLINK_MELONDS"
            print(f"SKIP ds_to_pc: {reason}", flush=True)
            ctx.artifacts.record("ds_to_pc", "SKIP", "EMULATOR",
                                 reason=reason)
        if ctx.environment.azahar:
            _scenario(ctx, "3ds_boot")
        else:
            reason = "Azahar ausente; instale/configure CHESTLINK_AZAHAR"
            print(f"SKIP 3ds_boot: {reason}", flush=True)
            ctx.artifacts.record("3ds_boot", "SKIP", "EMULATOR",
                                 reason=reason)
    else:
        if emulator_mode == "none":
            reason = "emulator_mode=none"
        else:
            reason = (
                "execução não interativa (stdin sem terminal); execute "
                "make e2e-ds-to-pc e make e2e-3ds em terminal gráfico"
            )
        for name in ("ds_to_pc", "3ds_boot"):
            print(f"SKIP {name}: {reason}", flush=True)
            ctx.artifacts.record(name, "SKIP", "EMULATOR", reason=reason)
    return not any(row["status"] == "FAIL" for row in ctx.artifacts.results)


def _timeout_from_env():
    value = os.environ.get("CHESTLINK_E2E_TIMEOUT_SECONDS", "180")
    try:
        timeout = int(value)
    except ValueError:
        raise ValueError("CHESTLINK_E2E_TIMEOUT_SECONDS precisa ser inteiro.") from None
    if not 5 <= timeout <= 3600:
        raise ValueError("CHESTLINK_E2E_TIMEOUT_SECONDS deve estar entre 5 e 3600.")
    return timeout


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", nargs="?", default="all",
                        choices=("all", *SCENARIOS.keys()))
    parser.add_argument("--no-build", action="store_true",
                        help="não compila o par de consoles antes dos cenários")
    parser.add_argument("--emulators", choices=("auto", "none", "required"), default="auto",
                        help="auto roda emuladores apenas em terminal gráfico interativo")
    args = parser.parse_args(argv)
    try:
        timeout = _timeout_from_env()
    except ValueError as exc:
        parser.error(str(exc))

    environment = Environment.detect()
    artifacts = RunArtifacts(artifact_root())
    environment_data = {
        "platform": environment.platform,
        "display_session": environment.display_session,
        "melonDS_available": bool(environment.melon_ds),
        "Azahar_available": bool(environment.azahar),
        "screenshot_tool_available": bool(environment.screenshot_tool),
        "input_automation_available": bool(environment.input_tool),
        "real_hardware_tested": False,
    }
    print(f"E2E artifacts: {artifacts.path}", flush=True)
    ctx = RunContext(artifacts, environment, timeout, build=not args.no_build)
    success = False
    try:
        if args.scenario == "all":
            success = _all(ctx, args.emulators)
        else:
            if args.scenario in {"ds_boot", "3ds_boot", "ds_to_pc"} and ctx.build:
                # Emulator availability is checked by the scenario before a build starts.
                pass
            _scenario(ctx, args.scenario)
            success = not any(row["status"] == "FAIL" for row in artifacts.results)
    except KeyboardInterrupt:
        print("Interrompido; encerrando processos e preservando artifacts.", flush=True)
        artifacts.record("runner", "INTERRUPTED", "HOST", reason="Ctrl+C")
        success = False
    finally:
        result_path = artifacts.write_summary(args.scenario, environment_data)
        print(f"Resultado: {result_path}", flush=True)
    print("E2E " + ("PASS" if success else "FAIL"), flush=True)
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
