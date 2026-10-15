"""Process tracking with process-group cleanup and private logs."""
import os
from pathlib import Path
import signal
import subprocess
import time
import re


class ProcessError(RuntimeError):
    pass


class ManagedProcess:
    def __init__(self, name, argv, process, log_path, log_stream):
        self.name = name
        self.argv = tuple(str(arg) for arg in argv)
        self.process = process
        self.log_path = Path(log_path)
        self._log_stream = log_stream
        self.container_id_path = None

    def poll(self):
        return self.process.poll()

    def stop(self, grace_seconds=4, first_signal=signal.SIGTERM):
        # Stop the container while its Podman client/conmon still exists.
        # Killing the launcher first can leave an orphaned emulator behind.
        if self.container_id_path and self.container_id_path.is_file():
            container_id = self.container_id_path.read_text().strip()
            if re.fullmatch(r"[0-9a-f]{64}", container_id):
                subprocess.run(["podman", "rm", "--force", container_id],
                               capture_output=True, timeout=15, check=False)
        # AppImage launchers may exit while their GUI child keeps running in
        # the session. Always address the owned group, even after leader exit.
        try:
            os.killpg(self.process.pid, 0)
            group_alive = True
        except ProcessLookupError:
            group_alive = False
        if group_alive:
            try:
                os.killpg(self.process.pid, first_signal)
            except ProcessLookupError:
                pass
            deadline = time.monotonic() + grace_seconds
            while time.monotonic() < deadline:
                self.process.poll()
                try:
                    os.killpg(self.process.pid, 0)
                except ProcessLookupError:
                    break
                time.sleep(0.05)
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            raise ProcessError(f"O processo {self.name} não encerrou após SIGKILL.") from None
        finally:
            if not self._log_stream.closed:
                self._log_stream.close()
        return self.process.returncode


class ProcessRegistry:
    def __init__(self):
        self._processes = []

    def start(self, name, argv, log_path, *, cwd, env=None):
        log_path = Path(log_path)
        log_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        stream = log_path.open("wb")
        os.chmod(log_path, 0o600)
        try:
            process = subprocess.Popen(
                [str(part) for part in argv], cwd=str(cwd), env=env,
                stdin=subprocess.DEVNULL, stdout=stream, stderr=subprocess.STDOUT,
                start_new_session=True, close_fds=True,
            )
        except BaseException:
            stream.close()
            raise
        managed = ManagedProcess(name, argv, process, log_path, stream)
        if env and env.get("CHESTLINK_E2E_CONTAINER_ID"):
            managed.container_id_path = Path(env["CHESTLINK_E2E_CONTAINER_ID"])
        self._processes.append(managed)
        return managed

    def stop(self, process, *, first_signal=signal.SIGTERM):
        return process.stop(first_signal=first_signal)

    def stop_all(self):
        errors = []
        # Finish cleanup even if a second termination request arrives while
        # Podman is stopping a GUI container.
        previous = signal.signal(signal.SIGTERM, signal.SIG_IGN)
        try:
            for process in reversed(self._processes):
                try:
                    process.stop()
                except (ProcessError, OSError, subprocess.TimeoutExpired) as exc:
                    errors.append(str(exc))
            self._processes.clear()
        finally:
            signal.signal(signal.SIGTERM, previous)
        if errors:
            raise ProcessError("; ".join(errors))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.stop_all()
        return False


def log_tail(path, max_lines=40):
    try:
        lines = Path(path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return "(log indisponível)"
    return "\n".join(lines[-max_lines:]) or "(log vazio)"
