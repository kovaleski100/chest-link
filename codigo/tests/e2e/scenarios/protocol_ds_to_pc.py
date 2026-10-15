"""End-to-end console-shared C++ mailbox protocol against a native server."""
import re
import subprocess

from tests.e2e.config import ROOT
from tests.e2e.scenarios.common import (
    TEST_PIN, create_synthetic_bank, start_pc_server, stop_server,
    validate_received_item, wait_server_ready,
)


def run(ctx):
    build = subprocess.run(["make", "-C", str(ROOT), "build/chest-link-cli"],
                           text=True, capture_output=True, timeout=180, check=False)
    build_log = ctx.artifacts.path / "logs" / "host-client-build.log"
    build_log.write_text(build.stdout + build.stderr, encoding="utf-8")
    if build.returncode:
        raise RuntimeError(f"Não foi possível compilar o cliente host; veja {build_log}")
    fixture = create_synthetic_bank(ctx.artifacts.path / "artifacts" / "synthetic-bank")
    start_pc_server(ctx, pin=TEST_PIN)
    try:
        wait_server_ready(ctx)
        before = set()
        command = [str(ROOT / "build" / "chest-link-cli"), "mail-send",
                   str(fixture["store"]), "e2e", "1", "127.0.0.1", str(TEST_PIN),
                   "0", str(ctx.server["tcp_port"])]
        result = subprocess.run(command, cwd=ROOT, text=True, capture_output=True,
                                timeout=30, check=False)
        client_log = ctx.artifacts.path / "logs" / "protocol-client.log"
        client_log.write_text(result.stdout + result.stderr, encoding="utf-8")
        if result.returncode:
            raise RuntimeError("Cliente C++ recusou a transferência; veja " + str(client_log))
        match = re.search(r"\bSTORED\s+([0-9a-f]{32})\b", result.stdout)
        if not match:
            raise RuntimeError("O cliente não recebeu ACK estruturado STORED.")
        item_id = match.group(1)
        metrics = validate_received_item(ctx, item_id, fixture)
        clean = stop_server(ctx)
        if not clean:
            raise AssertionError("O servidor deixou a porta TCP aberta após encerrar.")
        metrics.update({"direction": "console_to_pc_protocol", "client_adapter": "CL_HOST",
                        "source_fixture": "synthetic_public", "clean_shutdown": clean})
        return ctx.artifacts.record(
            "protocol_ds_to_pc", "PASS", "HOST_PROTOCOL",
            reason="Executa o protocolo C++ compartilhado; não equivale a emulador nem a hardware.",
            metrics=metrics,
            artifacts=[str(ctx.server["process"].log_path), str(client_log), str(build_log)],
        )
    finally:
        if ctx.server and ctx.server["process"].poll() is None:
            stop_server(ctx)
