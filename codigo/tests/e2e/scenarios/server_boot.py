"""Native PC-server boot and isolated interface/API readiness scenario."""
from tests.e2e.scenarios.common import start_pc_server, stop_server, wait_server_ready


def run(ctx):
    start_pc_server(ctx)
    try:
        state = wait_server_ready(ctx)
        if state.get("items") != [] or state.get("unassigned") != 0:
            raise AssertionError("O storage temporário do servidor não começou vazio.")
        clean = stop_server(ctx)
        if not clean:
            raise AssertionError("O servidor deixou a porta TCP aberta após encerrar.")
        return ctx.artifacts.record(
            "server_boot", "PASS", "HOST",
            metrics={"tcp_ready": True, "web_ready": True, "api_ready": True,
                     "isolated_data": str(ctx.server["data_root"]), "clean_shutdown": clean},
            artifacts=[str(ctx.server["process"].log_path)],
        )
    finally:
        if ctx.server and ctx.server["process"].poll() is None:
            stop_server(ctx)
