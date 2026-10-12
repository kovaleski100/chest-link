"""Local PC box interface. Standard-library HTTP; console TCP is unchanged.

The GUI reads verified snapshots and republishes copies through the same TCP
upload path as a console. It preserves saved bytes; explicit requeue can mark
an identical delivered copy as pending again.
"""
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import ipaddress
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


def persistent_ui_token(core, data_root):
    path = Path(data_root) / "interface-token.json"
    try:
        saved = core.json_read(path)
    except FileNotFoundError:
        token = secrets.token_urlsafe(32)
        core.atomic_json(path, {"token": token})
        try:
            path.chmod(0o600)
        except OSError:
            pass
        return token
    except (OSError, ValueError, core.MailboxError):
        raise core.MailboxError("Arquivo do link da interface invalido; preserve a pasta de dados.") from None
    token = saved.get("token") if isinstance(saved, dict) and set(saved) == {"token"} else None
    if (not isinstance(token, str) or len(token) != 43 or not token.isascii() or
            any(not (char.isalnum() or char in "_-") for char in token)):
        raise core.MailboxError("Arquivo do link da interface invalido; preserve a pasta de dados.")
    return token


class Interface:
    def __init__(self, core, mailbox, tcp_address, addresses, web_port=8765,
                 web_bind="0.0.0.0", web_addresses=None, hotspot=None):
        self.core, self.mailbox = core, mailbox
        self.hotspot = hotspot
        host, port = tcp_address
        self.tcp_address = ("127.0.0.1" if host == "0.0.0.0" else host, port)
        self.addresses = addresses
        self.token = persistent_ui_token(core, mailbox.root)
        web_addresses = addresses if web_addresses is None else web_addresses
        self.web_addresses = [ip for ip in web_addresses
                              if ip != "0.0.0.0" and not ip.startswith("127.")]
        try:
            self.server = LocalServer((web_bind, web_port), self)
        except OSError:
            if web_port != 8765:
                raise
            self.server = LocalServer((web_bind, 0), self)
        self.thread = threading.Thread(target=self.server.serve_forever,
                                       kwargs={"poll_interval": .1}, daemon=True)
        self.url = f"http://127.0.0.1:{self.server.server_port}/#{self.token}"
        self.network_urls = [f"http://{ip}:{self.server.server_port}/#{self.token}"
                             for ip in self.web_addresses]
        self.allowed_hosts = {f"{host}:{self.server.server_port}"
                              for host in ("127.0.0.1", "localhost", *self.web_addresses)}
        if web_bind not in ("0.0.0.0", "127.0.0.1"):
            self.allowed_hosts.add(f"{web_bind}:{self.server.server_port}")
        # Published bank bytes are immutable; metadata changes only on delivery.
        self.verified = {}
        self.verify_lock = threading.Lock()
        self.action_lock = threading.RLock()
        self.species_cache = {}
        self.dex_state_file = self.mailbox.root / "pokedex-state.json"
        self.dex_lock = threading.Lock()
        self.mailbox.on_stored = self.mark_server_captured

    def start(self, open_browser=True):
        self.thread.start()
        if open_browser:
            threading.Thread(target=lambda: webbrowser.open(self.url), daemon=True).start()

    def close(self):
        if self.hotspot:
            with self.action_lock:
                try:
                    self.hotspot.close()
                except RuntimeError as exc:
                    print(f"A rede DS precisa de limpeza manual: {exc}", flush=True)
        if self.thread.is_alive():
            self.server.shutdown()
            self.thread.join(timeout=5)
        self.server.server_close()

    def state(self, can_manage_hotspot=False):
        with self.mailbox.lock:
            rows = sorted(self.mailbox.all_metadata(), key=lambda m: (m["created"], m["id"]), reverse=True)
        data = dict(version="0.4", pin=f"{self.mailbox.pin:06d}", port=self.tcp_address[1],
                    ips=self.addresses, items=rows,
                    unassigned=sum(m["target"] == 0 for m in rows),
                    ds=sum(m["target"] == 1 and not m["delivered"] and not m["queue_cleared"] for m in rows),
                    threeds=sum(m["target"] == 2 and not m["delivered"] and not m["queue_cleared"] for m in rows))
        data["hotspot"] = (self.hotspot.state(can_manage=can_manage_hotspot)
                            if self.hotspot else dict(available=False, running=False,
                                                      canManage=False,
                                                      reason="Controle de rede indisponível."))
        return data

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
        with self.mailbox.delivery_lock:
            meta, folder = self.checked_item(item_id)
            if type(index) is not int or not 0 <= index < meta["offer"]["boxes"]:
                raise self.core.MailboxError("Box fora da copia.")
            names = json.loads((folder / "names.json").read_text())
            with (folder / "bank.bnk").open("rb") as f:
                f.seek(16 + index * self.core.BOX_BYTES)
                entries = f.read(self.core.BOX_BYTES)
            return dict(id=item_id, box=index, boxes=meta["offer"]["boxes"], name=names[index],
                        pokemon=[pokemon.preview(entries[i * 336:(i + 1) * 336]) for i in range(30)])

    def clear_pending(self, request):
        if request != {}:
            raise self.core.MailboxError("Pedido para limpar pendencias invalido.")
        cleared = self.mailbox.clear_pending()
        return dict(cleared=len(cleared))

    @staticmethod
    def empty_dex_state():
        return dict(version=3, mode="unified", unified=[], legacyGreen=[], serverCaptured=[],
                    individual={game: [] for game in ("red", "blue", "yellow")})

    def read_dex_state(self):
        try:
            data = json.loads(self.dex_state_file.read_text(encoding="utf-8"),
                              object_pairs_hook=self.core.no_duplicates)
        except FileNotFoundError:
            return self.empty_dex_state()
        if (not isinstance(data, dict) or data.get("mode") not in ("unified", "individual") or
                not isinstance(data.get("unified"), list) or not isinstance(data.get("individual"), dict)):
            raise self.core.MailboxError("Arquivo de progresso da Pokedex invalido; os dados foram preservados.")
        if (data.get("version") == 1 and set(data) == {"version", "mode", "unified", "individual"} and
                set(data["individual"]) == {"red", "green", "blue", "yellow"}):
            data = dict(version=3, mode=data["mode"], unified=data["unified"],
                        individual={game: data["individual"][game] for game in ("red", "blue", "yellow")},
                        legacyGreen=data["individual"]["green"], serverCaptured=[])
        elif (data.get("version") == 2 and
              set(data) == {"version", "mode", "unified", "individual", "legacyGreen"} and
              set(data["individual"]) == {"red", "blue", "yellow"}):
            data = dict(version=3, mode=data["mode"], unified=data["unified"],
                        individual=data["individual"], legacyGreen=data["legacyGreen"], serverCaptured=[])
        elif (data.get("version") != 3 or
              set(data) != {"version", "mode", "unified", "individual", "legacyGreen", "serverCaptured"} or
              set(data["individual"]) != {"red", "blue", "yellow"}):
            raise self.core.MailboxError("Arquivo de progresso da Pokedex invalido; os dados foram preservados.")
        if not isinstance(data.get("legacyGreen"), list):
            raise self.core.MailboxError("Progresso legado da Pokedex invalido; os dados foram preservados.")
        for values in [data["unified"], data["legacyGreen"], data["serverCaptured"], *data["individual"].values()]:
            if (not isinstance(values, list) or any(type(value) is not int or not 1 <= value <= 151
                                                   for value in values) or
                    len(values) != len(set(values))):
                raise self.core.MailboxError("Progresso da Pokedex invalido; os dados foram preservados.")
        return data

    def mark_server_captured(self, folder, offer):
        species = set()
        with (folder / "bank.bnk").open("rb") as stream:
            stream.seek(16)
            for _ in range(offer["boxes"] * 30):
                entry = stream.read(336)
                if len(entry) != 336:
                    raise self.core.MailboxError("Copia incompleta ao marcar capturas da Pokedex.")
                summary = pokemon.preview(entry)
                if summary["valid"] and 1 <= summary["species"] <= 151:
                    species.add(summary["species"])
        if not species:
            return
        with self.dex_lock:
            data = self.read_dex_state()
            captured = sorted(set(data["serverCaptured"]) | species)
            if captured != data["serverCaptured"]:
                data["serverCaptured"] = captured
                self.core.atomic_json(self.dex_state_file, data)

    def update_pokedex(self, request):
        games = ("red", "blue", "yellow")
        if (not isinstance(request, dict) or set(request) != {"mode", "game", "species", "captured"} or
                request["mode"] not in ("unified", "individual") or request["game"] not in games or
                type(request["species"]) is not int or not 1 <= request["species"] <= 151 or
                type(request["captured"]) is not bool):
            raise self.core.MailboxError("Atualizacao da Pokedex invalida.")
        with self.dex_lock:
            data = self.read_dex_state()
            if data["mode"] != request["mode"]:
                if request["mode"] == "unified":
                    data["unified"] = sorted({species for values in data["individual"].values()
                                              for species in values})
                    for game in games:
                        data["individual"][game] = list(data["unified"])
                else:
                    for game in games:
                        data["individual"][game] = list(data["unified"])
                data["mode"] = request["mode"]
            collection = set(data["unified"] if data["mode"] == "unified"
                             else data["individual"][request["game"]])
            if request["captured"]:
                collection.add(request["species"])
            else:
                collection.discard(request["species"])
            if data["mode"] == "unified":
                data["unified"] = sorted(collection)
                for game in games:
                    data["individual"][game] = list(data["unified"])
            else:
                data["individual"][request["game"]] = sorted(collection)
            self.core.atomic_json(self.dex_state_file, data)
        return self.pokedex()

    def pokedex(self):
        with self.dex_lock:
            progress = self.read_dex_state()
        with self.mailbox.lock:
            rows = list(self.mailbox.all_metadata())
        counts = {}
        for row in rows:
            meta, folder = self.checked_item(row["id"])
            bank = folder / "bank.bnk"
            signature = (bank.stat().st_size, bank.stat().st_mtime_ns)
            with self.verify_lock:
                cached = self.species_cache.get(row["id"])
                if cached and cached[0] == signature:
                    species_counts = cached[1]
                else:
                    species_counts = None
            if species_counts is None:
                species_counts = {}
                with bank.open("rb") as stream:
                    stream.seek(16)
                    for _ in range(meta["offer"]["boxes"] * 30):
                        entry = stream.read(336)
                        if len(entry) != 336:
                            raise self.core.MailboxError("Copia incompleta ao atualizar a Pokedex.")
                        summary = pokemon.preview(entry)
                        if summary["valid"] and 1 <= summary["species"] <= 151:
                            species_id = summary["species"]
                            species_counts[species_id] = species_counts.get(species_id, 0) + 1
                with self.verify_lock:
                    self.species_cache[row["id"]] = (signature, species_counts)
            for species_id, count in species_counts.items():
                counts[species_id] = counts.get(species_id, 0) + count
        with self.dex_lock:
            progress = self.read_dex_state()
            captured = sorted(set(progress["serverCaptured"]) | set(counts))
            if captured != progress["serverCaptured"]:
                progress["serverCaptured"] = captured
                self.core.atomic_json(self.dex_state_file, progress)
        return dict(mode=progress["mode"], unified=progress["unified"],
                    individual=progress["individual"], serverCounts=counts,
                    serverCaptured=progress["serverCaptured"])

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
        # An archived or previously delivered identical snapshot has the same
        # ID. Explicitly sending it again restores its queue entry; bytes stay intact.
        with self.mailbox.lock:
            queued = self.mailbox.metadata(item_id)
            if queued["delivered"] or queued["queue_cleared"]:
                queued["delivered"] = 0
                queued["queue_cleared"] = 0
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
        if self.headers.get("Host") not in self.server.interface.allowed_hosts:
            self.send(403, dict(error="Endereco da interface nao autorizado."))
            return False
        return True

    def authenticated(self):
        supplied = self.headers.get("Authorization", "")
        if not secrets.compare_digest(supplied, "Bearer " + self.server.interface.token):
            self.send(401, dict(error="Abra a interface pelo link exibido no servidor."))
            return False
        return True

    def local_client(self):
        try:
            return ipaddress.ip_address(self.client_address[0]).is_loopback
        except ValueError:
            return False

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
                    self.send(200, interface.state(can_manage_hotspot=self.local_client()))
                elif url.path == "/api/pokedex":
                    self.send(200, interface.pokedex())
                elif url.path == "/api/box":
                    args = parse_qs(url.query, strict_parsing=True)
                    if set(args) != {"id", "box"} or any(len(v) != 1 for v in args.values()):
                        raise interface.core.MailboxError("Pedido de box invalido.")
                    self.send(200, interface.box(args["id"][0], int(args["box"][0])))
                else:
                    self.send(404, dict(error="Tela nao encontrada."))
                return
            relative = "index.html" if url.path == "/" else url.path.lstrip("/")
            if relative not in {"index.html", "app.js", "style.css", "dex.css"} and not (
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
            if self.path not in {"/api/requeue", "/api/send-direct", "/api/clear-pending", "/api/pokedex", "/api/hotspot"}:
                self.send(404, dict(error="Acao nao encontrada."))
                return
            if self.path == "/api/hotspot":
                if not self.local_client():
                    self.send(403, dict(error="Inicie ou encerre a rede DS pelo navegador deste PC."))
                    return
                if (not isinstance(request, dict) or set(request) != {"action"} or
                        request["action"] not in ("start", "stop")):
                    raise interface.core.MailboxError("Ação da rede DS inválida.")
                if not interface.hotspot:
                    raise interface.core.MailboxError("O controle de rede DS não está disponível.")
                with interface.action_lock:
                    result = (interface.hotspot.start() if request["action"] == "start"
                              else interface.hotspot.stop())
                self.send(200, result)
            elif self.path == "/api/pokedex":
                result = interface.update_pokedex(request)
            elif self.path == "/api/clear-pending":
                with interface.action_lock:
                    result = interface.clear_pending(request)
            else:
                with interface.action_lock:
                    result = interface.send_direct(request) if self.path == "/api/send-direct" else interface.requeue(request)
            self.send(200, result)
        except (interface.core.MailboxError, OSError, ValueError, KeyError, TypeError,
                RecursionError, RuntimeError) as exc:
            self.send(400, dict(error=str(exc)))
