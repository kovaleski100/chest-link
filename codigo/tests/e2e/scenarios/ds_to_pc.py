"""Semi-automated melonDS to native PC mailbox transfer."""
from tests.e2e.artifacts import capture_screenshot
from tests.e2e.scenarios.common import (
    discover_host_ips, start_pc_server, tcp_port_available,
    stop_server, validate_received_item, wait_for_new_item, wait_server_ready,
)
from tests.e2e.scenarios.emulator_boot import ScenarioSkipped, ensure_console_pair, start_ds


def run(ctx):
    if not ctx.environment.melon_ds:
        raise ScenarioSkipped("melonDS não está instalado; defina CHESTLINK_MELONDS")
    if ctx.environment.display_session == "headless":
        raise ScenarioSkipped("DS→PC no melonDS precisa de sessão gráfica e input manual")
    if not tcp_port_available("0.0.0.0", 40992):
        raise ScenarioSkipped(
            "porta TCP 40992 indisponível; o listener existente foi preservado"
        )
    ensure_console_pair(ctx)
    start_pc_server(ctx, bind="0.0.0.0", tcp_port=40992, pin=None)
    emulator = None
    try:
        initial_state = wait_server_ready(ctx)
        before_ids = {row["id"] for row in initial_state.get("items", [])}
        pin = initial_state.get("pin")
        ips = discover_host_ips(initial_state)
        print("Servidor E2E em porta 40992. IPs detectados do PC: " +
              (", ".join(ips) if ips else "use o endereço de host mostrado pelo emulador") +
              f"; PIN: {pin or '(consulte logs/server.log)'}", flush=True)
        emulator, fixture, _rom, _profile, _storage = start_ds(ctx, transfer=True)
        print(
            "No melonDS: configure/conecte uma rede alcançável pelo PC; em Chest Link, "
            "abra Consultar bancos → e2e → escolha a box → enviar ao PC; digite o IP "
            "do host e o PIN acima. A origem é um banco sintético isolado.", flush=True)
        row = wait_for_new_item(ctx, before_ids, ctx.timeout_seconds, emulator=emulator)
        if row is None:
            screenshot = capture_screenshot(ctx.environment,
                                            ctx.artifacts.path / "screenshots" / "ds-to-pc-timeout.png")
            if screenshot:
                ctx.extra_artifacts.append(str(screenshot))
            raise TimeoutError("Nenhum novo item chegou à mailbox dentro do prazo.")
        metrics = validate_received_item(ctx, row["id"], fixture)
        ctx.processes.stop(emulator)
        clean = stop_server(ctx)
        if not clean:
            raise AssertionError("O servidor não encerrou/fechou a porta após a transferência.")
        metrics.update({"direction": "DS_to_PC", "menu_input": "manual", "wifi_setup": "manual",
                        "clean_shutdown": clean, "real_hardware_validated": False})
        return ctx.artifacts.record(
            "ds_to_pc", "PASS", "EMULATOR+HOST",
            reason="Transferência semiautomática no melonDS com confirmação por mailbox/ACK; não valida hardware real.",
            metrics=metrics,
            artifacts=[str(ctx.server["process"].log_path), str(ctx.artifacts.path / "ds" / "melonds.log")],
        )
    finally:
        if ctx.server and ctx.server["process"].poll() is None:
            stop_server(ctx)
