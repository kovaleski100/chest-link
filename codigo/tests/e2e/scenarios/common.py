"""Shared server and fixture helpers for E2E scenarios."""
import hashlib
import http.client
import json
from pathlib import Path
import signal
import socket
import struct
import sys
import time
from urllib.error import URLError
from urllib.request import Request, urlopen

from tests.e2e.config import ROOT


TEST_PIN = 314159


def free_port(host="127.0.0.1"):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return sock.getsockname()[1]


def tcp_port_available(host, port):
    """Check whether the requested TCP bind can be used without contacting its listener."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def create_synthetic_bank(store_root, box_name="E2E Test Box"):
    """Write a public-format one-box PKSMBANK fixture with one occupied slot."""
    store_root = Path(store_root)
    banks = store_root / "banks"
    banks.mkdir(parents=True, exist_ok=True, mode=0o700)
    bank = bytearray(b"PKSMBANK" + struct.pack("<II", 3, 1))
    for slot in range(30):
        entry = bytearray([0xFF] * 336)
        if slot == 0:
            entry[:4] = struct.pack("<I", 0)
            entry[4:332] = bytes([0x31]) * 328
        bank.extend(entry)
    (banks / "e2e.bnk").write_bytes(bank)
    (banks / "e2e.json").write_text(json.dumps([box_name], ensure_ascii=False) + "\n",
                                     encoding="utf-8")
    (store_root / "banks.json").write_text(json.dumps({"e2e": 1}) + "\n", encoding="utf-8")
    return {"store": store_root, "bank": banks / "e2e.bnk", "names": banks / "e2e.json",
            "bank_sha256": hashlib.sha256(bank).hexdigest(), "boxes": 1, "occupied": 1,
            "box_name": box_name}


def _request(url, *, token=None, timeout=2):
    headers = {}
    if token:
        headers["Authorization"] = "Bearer " + token
    request = Request(url, headers=headers)
    with urlopen(request, timeout=timeout) as response:
        return response.status, response.read()


def start_pc_server(ctx, *, bind="127.0.0.1", tcp_port=None, pin=TEST_PIN, reuse=False):
    """Start the real CLI server against a fresh per-run data directory."""
    tcp_port = tcp_port or free_port(bind)
    web_port = free_port("127.0.0.1")
    scenario_name = getattr(ctx, "scenario_name", "server")
    server_dir = ctx.artifacts.path / "server" / scenario_name
    data_root = server_dir / "data"
    data_root.mkdir(parents=True, mode=0o700, exist_ok=reuse)
    argv = [sys.executable, str(ROOT / "server" / "chest_link_server.py"),
            "--data", str(data_root), "--bind", bind, "--port", str(tcp_port),
            "--web-port", str(web_port), "--web-bind", "127.0.0.1", "--no-browser"]
    if pin is not None:
        argv.extend(("--pin", str(pin)))
    process = ctx.processes.start("chest-link-server", argv,
                                  ctx.artifacts.path / "logs" / f"{scenario_name}-server.log",
                                  cwd=ROOT, env=ctx.child_env())
    ctx.server = {"process": process, "data_root": data_root, "server_dir": server_dir,
                  "bind": bind,
                  "tcp_port": tcp_port, "web_port": web_port, "pin": pin}
    return ctx.server


def wait_server_ready(ctx, timeout_seconds=12):
    server = ctx.server
    deadline = time.monotonic() + timeout_seconds
    last_error = "servidor ainda não abriu as portas"
    page_url = f"http://127.0.0.1:{server['web_port']}/"
    api_url = f"http://127.0.0.1:{server['web_port']}/api/state"
    token_path = server["data_root"] / "interface-token.json"
    while time.monotonic() < deadline:
        if server["process"].poll() is not None:
            raise RuntimeError("O servidor encerrou durante a inicialização.")
        try:
            with socket.create_connection(("127.0.0.1", server["tcp_port"]), timeout=0.25):
                pass
            status, body = _request(page_url, timeout=0.75)
            if status != 200 or b"<html" not in body.lower():
                raise RuntimeError("A interface web não retornou HTML.")
            if token_path.is_file():
                token = json.loads(token_path.read_text(encoding="utf-8"))["token"]
                status, body = _request(api_url, token=token, timeout=0.75)
                state = json.loads(body)
                if status == 200 and state.get("port") == server["tcp_port"]:
                    return state
            last_error = "API ainda não está pronta"
        except (OSError, ValueError, KeyError, URLError, http.client.HTTPException) as exc:
            last_error = str(exc)
        time.sleep(0.1)
    raise TimeoutError(f"Servidor não ficou pronto em {timeout_seconds}s: {last_error}")


def read_server_state(ctx):
    server = ctx.server
    token_path = server["data_root"] / "interface-token.json"
    token = json.loads(token_path.read_text(encoding="utf-8"))["token"]
    status, body = _request(f"http://127.0.0.1:{server['web_port']}/api/state", token=token)
    if status != 200:
        raise RuntimeError("A API de estado do servidor recusou o pedido local.")
    return json.loads(body)


def discover_host_ips(state):
    return [address for address in state.get("ips", []) if address and address != "127.0.0.1"]


def validate_received_item(ctx, item_id, expected):
    state = read_server_state(ctx)
    row = next((item for item in state.get("items", []) if item.get("id") == item_id), None)
    if row is None:
        raise AssertionError("A API não listou o pacote recém-enviado.")
    offer = row.get("offer", {})
    if (row.get("target") != 0 or offer.get("boxes") != expected["boxes"] or
            offer.get("occupied") != expected["occupied"]):
        raise AssertionError("Quantidade de boxes/Pokémon no pacote recebido não confere.")
    item_root = ctx.server["data_root"] / "items" / item_id
    bank_path, names_path = item_root / "bank.bnk", item_root / "names.json"
    bank, names = bank_path.read_bytes(), names_path.read_bytes()
    digest = hashlib.sha256(bank + names).hexdigest()
    if digest != offer.get("hash"):
        raise AssertionError("SHA-256 do pacote salvo difere do ACK do servidor.")
    parsed_names = json.loads(names.decode("utf-8"))
    if parsed_names != [expected["box_name"]]:
        raise AssertionError("O nome da box no pacote recebido não confere.")
    if len(bank) != 16 + 10080 or bank[:8] != b"PKSMBANK":
        raise AssertionError("Cabeçalho/tamanho do banco recebido não confere.")
    return {"item_id": item_id, "boxes": offer["boxes"], "pokemon": offer["occupied"],
            "bank_sha256": hashlib.sha256(bank).hexdigest(), "package_sha256": digest,
            "mailbox_pending": True, "server_ack": True}


def wait_for_new_item(ctx, before_ids, timeout_seconds, *, emulator=None):
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        if ctx.server["process"].poll() is not None:
            raise RuntimeError("O servidor encerrou enquanto aguardava a transferência.")
        if emulator is not None and emulator.poll() is not None:
            raise RuntimeError(f"melonDS encerrou durante a transferência (código {emulator.poll()}).")
        state = read_server_state(ctx)
        rows = [row for row in state.get("items", []) if row.get("id") not in before_ids]
        if rows:
            return rows[0]
        time.sleep(0.25)
    return None


def stop_server(ctx):
    if not ctx.server:
        return True
    process = ctx.server["process"]
    ctx.processes.stop(process, first_signal=signal.SIGINT)
    try:
        with socket.create_connection(("127.0.0.1", ctx.server["tcp_port"]), timeout=0.2):
            return False
    except OSError:
        return True
