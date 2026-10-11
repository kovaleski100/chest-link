"""Local PC box interface. Standard-library HTTP; console TCP is unchanged.

The GUI reads verified snapshots and republishes copies through the same TCP
upload path as a console. It preserves saved bytes; explicit requeue can mark
an identical delivered copy as pending again.
"""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import socket
import struct
import threading
from urllib.parse import parse_qs, urlsplit
import webbrowser

try:
    from . import pokemon
except ImportError:
    import pokemon

WEB = Path(__file__).resolve().parent / "web"
ALL_SLOTS = (1 << 30) - 1


class Interface:
    def __init__(self, core, mailbox, tcp_address, addresses, web_port=8765):
        self.core, self.mailbox = core, mailbox
        host, port = tcp_address
        self.tcp_address = ("127.0.0.1" if host == "0.0.0.0" else host, port)
        self.addresses = addresses
        self.token = secrets.token_urlsafe(32)
        try:
            self.server = LocalServer(("127.0.0.1", web_port), self)
        except OSError:
            if web_port != 8765:
                raise
            self.server = LocalServer(("127.0.0.1", 0), self)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": .1}, daemon=True)
        self.url = f"http://127.0.0.1:{self.server.server_port}/#{self.token}"
        # Published bank bytes are immutable; metadata changes only on delivery.
        self.verified = {}
        self.verify_lock = threading.Lock()

    def start(self, open_browser=True):
        self.thread.start()
        if open_browser:
            threading.Thread(target=lambda: webbrowser.open(self.url), daemon=True).start()

    def close(self):
        if self.thread.is_alive():
            self.server.shutdown()
            self.thread.join(timeout=5)
        self.server.server_close()

    def state(self):
        with self.mailbox.lock:
            rows = sorted(self.mailbox.all_metadata(), key=lambda m: (m["created"], m["id"]), reverse=True)
        return dict(version="0.3", pin=f"{self.mailbox.pin:06d}", port=self.tcp_address[1],
                    ips=self.addresses, items=rows,
                    ds=sum(m["target"] == 1 and not m["delivered"] for m in rows),
                    threeds=sum(m["target"] == 2 and not m["delivered"] for m in rows))

    def checked_item(self, item_id):
        with self.mailbox.lock:
            meta = self.mailbox.metadata(item_id)
        folder = self.mailbox.items / item_id
        signatures = tuple((p.stat().st_size, p.stat().st_mtime_ns) for p in
                           (folder / "bank.bnk", folder / "names.json"))
        with self.verify_lock:
            if self.verified.get(item_id) != signatures:
                self.core.validate_package(folder, meta["offer"], meta["target"])
                self.verified[item_id] = signatures
        return meta, folder

    def box(self, item_id, index):
        meta, folder = self.checked_item(item_id)
        if type(index) is not int or not 0 <= index < meta["offer"]["boxes"]:
            raise self.core.MailboxError("Box fora da copia.")
        names = json.loads((folder / "names.json").read_text())
        with (folder / "bank.bnk").open("rb") as f:
            f.seek(16 + index * self.core.BOX_BYTES)
            entries = f.read(self.core.BOX_BYTES)
        return dict(id=item_id, box=index, boxes=meta["offer"]["boxes"], name=names[index],
                    pokemon=[pokemon.preview(entries[i * 336:(i + 1) * 336]) for i in range(30)])

    def requeue(self, request):
        if not isinstance(request, dict) or set(request) != {"id", "target", "masks"}:
            raise self.core.MailboxError("Pedido de selecao invalido.")
        self.core.target_check(request["target"])
        if not isinstance(request["id"], str):
            raise self.core.MailboxError("Identificador invalido.")
        meta, folder = self.checked_item(request["id"])
        masks = request["masks"]
        if not isinstance(masks, list) or len(masks) != meta["offer"]["boxes"] or any(
                type(m) is not int or not 0 <= m <= ALL_SLOTS for m in masks):
            raise self.core.MailboxError("Selecao de slots invalida.")
        included = [i for i, mask in enumerate(masks) if mask]
        if not included:
            raise self.core.MailboxError("Marque Pokemon ou uma box antes de enviar.")
        labels = json.loads((folder / "names.json").read_text())
        bank = bytearray(b"PKSMBANK" + struct.pack("<II", 3, len(included)))
        occupied = generations = 0
        with (folder / "bank.bnk").open("rb") as stream:
            for index in included:
                stream.seek(16 + index * self.core.BOX_BYTES)
                data = bytearray(stream.read(self.core.BOX_BYTES))
                if len(data) != self.core.BOX_BYTES:
                    raise self.core.MailboxError("Copia incompleta no PC.")
                for slot in range(30):
                    if not masks[index] & (1 << slot):
                        data[slot * 336:(slot + 1) * 336] = b"\xff" * 336
                    gen = struct.unpack_from("<I", data, slot * 336)[0]
                    if gen != 0xffffffff:
                        occupied += 1
                        generations |= 1 << gen
                bank.extend(data)
        names = json.dumps([labels[i] for i in included], ensure_ascii=False,
                           separators=(",", ":")).encode()
        offer = dict(boxes=len(included), occupied=occupied, generations=generations,
                     bankBytes=len(bank), namesBytes=len(names), hash=hashlib.sha256(bank + names).hexdigest())
        target = request["target"]
        self.core.preflight(offer, target)
        label = ("PC: " + meta["label"]).encode("utf-8")[:63].decode("utf-8", "ignore").encode("utf-8")
        item_id = self.core.packet_id(target, offer["hash"])
        with socket.create_connection(self.tcp_address, timeout=30) as sock:
            sock.sendall(struct.pack("<8sIII", b"CLMAIL01", 1, self.mailbox.pin, 1))
            self.core.result(sock)
            sock.sendall(struct.pack("<II", target, len(label)) + label + self.core.offer_encode(offer))
            status = self.core.result(sock)
            if status == "READY":
                sock.sendall(bank)
                sock.sendall(names)
                if self.core.result(sock) != item_id:
                    raise self.core.MailboxError("PC nao confirmou a copia esperada.")
            elif status != "STORED " + item_id:
                raise self.core.MailboxError("Resposta de armazenamento invalida.")
        # A previously delivered identical snapshot has the same ID. Sending
        # it again explicitly reopens its pending flag; all bytes stay intact.
        with self.mailbox.lock:
            queued = self.mailbox.metadata(item_id)
            if queued["delivered"]:
                queued["delivered"] = 0
                self.core.atomic_json(self.mailbox.items / item_id / "meta.json", queued)
        return dict(id=item_id, boxes=offer["boxes"], occupied=occupied, target=target)

    def send_direct(self, request):
        if not isinstance(request, dict) or set(request) != {"id", "target", "masks", "ip", "pin"}:
            raise self.core.MailboxError("Pedido de envio direto invalido.")
        ip = request["ip"]
        pin = request["pin"]
        if (not isinstance(ip, str) or not ip or len(ip) > 45 or
                type(pin) is not int or not 0 <= pin <= 999999):
            raise self.core.MailboxError("IP ou PIN do console invalido.")
        try:
            socket.inet_pton(socket.AF_INET, ip)
        except OSError:
            raise self.core.MailboxError("IP do console invalido.") from None
        selection = {key: request[key] for key in ("id", "target", "masks")}
        queued = self.requeue(selection)
        meta, folder = self.checked_item(queued["id"])
        try:
            with socket.create_connection((ip, 40991), timeout=30) as sock:
                sock.settimeout(180)
                sock.sendall(struct.pack("<8sII", b"CHESTLNK", 1, pin))
                self.core.result(sock)
                sock.sendall(self.core.offer_encode(meta["offer"]))
                self.core.result(sock)
                for name in ("bank.bnk", "names.json"):
                    with (folder / name).open("rb") as stream:
                        while True:
                            block = stream.read(4096)
                            if not block:
                                break
                            sock.sendall(block)
                received_name = self.core.result(sock)
        except OSError as exc:
            raise self.core.MailboxError("Nao foi possivel conectar ao listener do console: " + str(exc)) from None
        with self.mailbox.lock:
            delivered = self.mailbox.metadata(queued["id"])
            delivered["delivered"] = 1
            self.core.atomic_json(self.mailbox.items / queued["id"] / "meta.json", delivered)
        return dict(id=queued["id"], boxes=queued["boxes"], occupied=queued["occupied"],
                    target=queued["target"], bank=received_name)


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True
    def __init__(self, address, interface):
        self.interface = interface
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def send(self, status, data, mime="application/json; charset=utf-8"):
        if not isinstance(data, bytes):
            data = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(data)

    def local_request(self):
        port = self.server.server_port
        if self.headers.get("Host") not in (f"127.0.0.1:{port}", f"localhost:{port}"):
            self.send(403, dict(error="Interface disponivel apenas neste PC."))
            return False
        return True

    def authenticated(self):
        supplied = self.headers.get("Authorization", "")
        if not secrets.compare_digest(supplied, "Bearer " + self.server.interface.token):
            self.send(401, dict(error="Abra a interface pelo link exibido no servidor."))
            return False
        return True

    def do_GET(self):
        if not self.local_request():
            return
        interface = self.server.interface
        url = urlsplit(self.path)
        try:
            if url.path.startswith("/api/"):
                if not self.authenticated():
                    return
                if url.path == "/api/state":
                    self.send(200, interface.state())
                elif url.path == "/api/box":
                    args = parse_qs(url.query, strict_parsing=True)
                    if set(args) != {"id", "box"} or any(len(v) != 1 for v in args.values()):
                        raise interface.core.MailboxError("Pedido de box invalido.")
                    self.send(200, interface.box(args["id"][0], int(args["box"][0])))
                else:
                    self.send(404, dict(error="Tela nao encontrada."))
                return
            relative = "index.html" if url.path == "/" else url.path.lstrip("/")
            if relative not in {"index.html", "app.js", "style.css"} and not (
                    relative.startswith("assets/") and relative.count("/") == 1 and
                    relative[7:] in {p.name for p in (WEB / "assets").iterdir() if p.suffix in (".png", ".json")}):
                self.send(404, dict(error="Arquivo nao encontrado."))
                return
            mime = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                    ".css": "text/css; charset=utf-8", ".png": "image/png", ".json": "application/json"}
            self.send(200, (WEB / relative).read_bytes(), mime[Path(relative).suffix])
        except (interface.core.MailboxError, OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
            self.send(400, dict(error=str(exc)))

    def do_POST(self):
        if not self.local_request() or not self.authenticated():
            return
        interface = self.server.interface
        origin = self.headers.get("Origin")
        if origin != "http://" + self.headers.get("Host", ""):
            self.send(403, dict(error="Origem da pagina invalida."))
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 65536 or self.headers.get("Content-Type") != "application/json":
                raise interface.core.MailboxError("Pedido de selecao grande demais ou invalido.")
            self.connection.settimeout(15)
            data = self.rfile.read(length)
            if len(data) != length:
                raise interface.core.MailboxError("Pedido incompleto.")
            request = json.loads(data, object_pairs_hook=interface.core.no_duplicates)
            if self.path not in {"/api/requeue", "/api/send-direct"}:
                self.send(404, dict(error="Acao nao encontrada."))
                return
            result = interface.send_direct(request) if self.path == "/api/send-direct" else interface.requeue(request)
            self.send(200, result)
        except (interface.core.MailboxError, OSError, ValueError, KeyError, TypeError, RecursionError) as exc:
            self.send(400, dict(error=str(exc)))
