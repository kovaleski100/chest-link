#!/usr/bin/env python3
"""Chest Link: durable TCP mailbox and clean local box interface.

No third-party packages. Run with Python 3.9 or newer. Bank files are never
deleted on delivery; only the pending flag changes after the console's ACK.
"""
import argparse
import contextlib
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import secrets
import shutil
import socket
import socketserver
import struct
import sys
import threading
import time
import uuid

PORT = 40992
DISCOVERY_REQUEST = b"CLDSDISC"
DISCOVERY_RESPONSE = b"CLPCDISC"
UPDATE_TRACE_MAGIC = b"CLUPDLOG"
DISCOVERY_PACKET_BYTES = 12
MAX_BOXES, BOX_BYTES, ENTRY = 500, 10080, 336
MAX_NAMES = 256 * 1024
PAGE_SIZE = 32
UPDATE_MAGIC = b"CLUPD001"
MAX_UPDATE_BYTES = 16 * 1024 * 1024
UPDATE_SOCKET_TIMEOUT_SECONDS = 600
DS_UPDATE_ACK_TIMEOUT_SECONDS = 30
DS_UPDATE_PACE_SECONDS = 0.05
ID_RE = re.compile(r"[0-9a-f]{32}\Z")
LOG = logging.getLogger("chest-link")


class MailboxError(Exception):
    pass


class UpdateAudit:
    """Append update protocol milestones without recording secrets or payloads."""

    def __init__(self, server, peer_ip, console):
        self.session = uuid.uuid4().hex[:16]
        self.peer_ip = peer_ip
        self.console = console
        self.started = time.monotonic()
        self.path = server.update_log_path
        self.lock = server.update_log_lock
        self.event("session_started")

    def event(self, name, **fields):
        entry = {
            "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "elapsed_ms": round((time.monotonic() - self.started) * 1000),
            "session": self.session,
            "peer_ip": self.peer_ip,
            "console": self.console,
            "event": name,
        }
        entry.update(fields)
        try:
            encoded = json.dumps(entry, ensure_ascii=True, sort_keys=True) + "\n"
            with self.lock, self.path.open("a", encoding="utf-8") as stream:
                stream.write(encoded)
                stream.flush()
        except OSError as error:
            LOG.warning("Nao foi possivel gravar o log da atualizacao: %s", error)


class DiscoveryResponder:
    """Reply to local Chest Link UDP broadcasts so consoles can refresh the PC IP."""

    def __init__(self, address, server=None):
        self.server = server
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.socket.bind(address)
        self.socket.settimeout(0.2)
        self.address = self.socket.getsockname()
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self._serve, name="chest-link-discovery",
                                       daemon=True)

    def start(self):
        self.thread.start()
        return self

    def _serve(self):
        while not self.stopping.is_set():
            try:
                packet, source = self.socket.recvfrom(1200)
            except socket.timeout:
                continue
            except OSError:
                break
            if (packet.startswith(UPDATE_TRACE_MAGIC) and self.server is not None):
                self.server.record_update_telemetry(source[0], packet[len(UPDATE_TRACE_MAGIC):])
                continue
            if (len(packet) != DISCOVERY_PACKET_BYTES or
                    packet[:8] != DISCOVERY_REQUEST):
                continue
            try:
                self.socket.sendto(DISCOVERY_RESPONSE + packet[8:], source)
            except OSError:
                if self.stopping.is_set():
                    break

    def close(self):
        self.stopping.set()
        try:
            self.socket.close()
        finally:
            if self.thread.is_alive():
                self.thread.join(timeout=1)


def find_console_update(console):
    """Find a built console app whose release manifest matches its bytes."""
    script = Path(__file__).resolve()
    roots = (script.parent.parent, script.parent.parent.parent)
    if console == "3DS":
        relative_images = (Path("3ds/ChestLink_3DS/ChestLink_3DS.3dsx"),
                           Path("codigo/platform/3ds/ChestLink_3DS.3dsx"))
    elif console == "DS":
        relative_images = (Path("DS/ChestLink_DS.nds"),
                           Path("codigo/platform/nds/ChestLink_DS.nds"))
    else:
        raise ValueError("Console de atualizacao invalido.")
    for root in roots:
        images = tuple(root / relative for relative in relative_images)
        for image in images:
            manifest_path = image.with_name("release.json")
            if not image.is_file() or not manifest_path.is_file():
                continue
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                size = image.stat().st_size
                digest = hashlib.sha256(image.read_bytes()).hexdigest()
                if (not isinstance(manifest, dict) or set(manifest) !=
                        {"format", "version", "size", "sha256"} or
                        type(manifest["format"]) is not int or manifest["format"] != 1 or
                        type(manifest["version"]) is not int or
                        not 0 < manifest["version"] <= 0xffffff or
                        type(manifest["size"]) is not int or manifest["size"] != size or
                        not isinstance(manifest["sha256"], str) or
                        not re.fullmatch(r"[0-9a-f]{64}", manifest["sha256"]) or
                        manifest["sha256"] != digest or not 1 <= size <= MAX_UPDATE_BYTES):
                    continue
                return image, manifest["version"]
            except (OSError, ValueError, TypeError):
                continue
    return None, 0


def find_3ds_update():
    return find_console_update("3DS")


def find_nds_update():
    return find_console_update("DS")


class DSUpdateFlowControl:
    """Keep only one TCP segment outstanding to the NTR software receiver.

    The old DS client speaks the same byte stream. No new client ACK or
    protocol version is needed to download this fix with an installed app.
    """

    def __init__(self, sock, audit=None):
        self.socket = sock
        self.audit = audit
        self.mode = "paced"
        self.chunk_bytes = 256
        self.previous_nodelay = None
        if sock.family == getattr(socket, "AF_UNIX", None):
            self.mode = "local"
            self.chunk_bytes = 16 * 1024
        else:
            try:
                self.previous_nodelay = sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                if sys.platform.startswith("linux") and hasattr(socket, "TCP_INFO"):
                    info = self._tcp_info()
                    self.mode = "tcp-ack"
                    self.chunk_bytes = min(1024, info["mss"])
            except OSError:
                # Other PC systems still avoid the old multi-segment burst.
                # Do not label this timer-based fallback as ACK confirmation.
                pass
        if audit:
            audit.event("transfer_flow_control", mode=self.mode,
                        chunk_bytes=self.chunk_bytes,
                        ack_timeout_seconds=DS_UPDATE_ACK_TIMEOUT_SECONDS)

    def _tcp_info(self):
        # Linux UAPI struct tcp_info: these offsets are stable, including on
        # 32-bit hosts. Native endian, with explicit offsets (no ABI padding).
        info = self.socket.getsockopt(socket.IPPROTO_TCP, socket.TCP_INFO, 192)
        if len(info) < 148:
            raise OSError("TCP_INFO sem contadores de entrega")
        mss, = struct.unpack_from("=I", info, 16)
        if not mss:
            raise OSError("TCP_INFO sem MSS valido")
        return dict(state=info[0], mss=mss,
                    unacked=struct.unpack_from("=I", info, 24)[0],
                    notsent=struct.unpack_from("=I", info, 144)[0])

    def wait(self):
        if self.mode == "local":
            return
        if self.mode == "paced":
            time.sleep(DS_UPDATE_PACE_SECONDS)
            return
        started = time.monotonic()
        next_log = started + 5
        while True:
            info = self._tcp_info()
            if info["state"] not in (1, 8):  # ESTABLISHED or CLOSE_WAIT.
                raise MailboxError("A conexao com o DS foi encerrada durante o envio.")
            if not info["unacked"] and not info["notsent"]:
                return
            now = time.monotonic()
            if now - started >= DS_UPDATE_ACK_TIMEOUT_SECONDS:
                if self.audit:
                    self.audit.event("tcp_ack_timeout", **info)
                raise MailboxError(f"O DS nao confirmou o recebimento dos dados em "
                                   f"{DS_UPDATE_ACK_TIMEOUT_SECONDS:g} segundos.")
            if self.audit and now >= next_log:
                self.audit.event("tcp_ack_wait", wait_ms=round((now - started) * 1000),
                                 **info)
                next_log = now + 5
            time.sleep(0.005)

    def close(self):
        if self.previous_nodelay is not None:
            with contextlib.suppress(OSError):
                self.socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY,
                                       self.previous_nodelay)


def serve_update(sock, image, version, console="3DS", audit=None):
    """Send a verified console app only after the PIN-authenticated client accepts."""
    if image is None or not version:
        if audit:
            audit.event("update_unavailable")
        reply(sock, f"Atualizacao {console} indisponivel neste pacote.", ok=False)
        return
    try:
        source = image.open("rb")
        size = source.seek(0, os.SEEK_END)
        source.seek(0)
        if not 1 <= size <= MAX_UPDATE_BYTES:
            source.close()
            reply(sock, f"Arquivo de atualizacao {console} invalido.", ok=False)
            return
        digest = hashlib.sha256()
        while True:
            block = source.read(64 * 1024)
            if not block:
                break
            digest.update(block)
        checksum = digest.digest()
        source.seek(0)
    except OSError:
        if audit:
            audit.event("update_file_read_failed")
        reply(sock, f"Nao foi possivel ler o app {console} no pacote do PC.", ok=False)
        return
    if audit:
        audit.event("update_image_verified", version=version, bytes=size,
                    sha256=checksum.hex(), filename=image.name)

    previous_timeout = sock.gettimeout()
    # The console presents a human confirmation prompt between sending this
    # offer and replying with its decision. Keep that prompt and the following
    # DS transfer from inheriting the short, general mailbox idle timeout.
    sock.settimeout(max(previous_timeout or 0, UPDATE_SOCKET_TIMEOUT_SECONDS))
    flow = None
    try:
        reply(sock)
        sock.sendall(struct.pack("<8sII32s", UPDATE_MAGIC, version, size, checksum))
        if audit:
            audit.event("offer_sent", version=version, bytes=size,
                        sha256=checksum.hex())
        decision_started = time.monotonic()
        decision, = struct.unpack("<I", exact(sock, 4))
        if audit:
            audit.event("decision_received", accepted=(decision == 1),
                        decision=decision,
                        wait_ms=round((time.monotonic() - decision_started) * 1000))
        if decision == 0:
            return
        if decision != 1:
            raise MailboxError("Decisao de atualizacao invalida.")
        if console == "DS":
            flow = DSUpdateFlowControl(sock, audit)
        reply(sock)
        if audit:
            audit.event("transfer_ack_sent")
        if flow:
            flow.wait()  # Deliver the start reply before the first file segment.
        streamed = hashlib.sha256()
        bytes_sent = 0
        chunk_index = 0
        next_checkpoint = 64 * 1024
        while True:
            block = source.read(flow.chunk_bytes if flow else 16 * 1024)
            if not block:
                break
            send_started = time.monotonic()
            sock.sendall(block)
            bytes_sent += len(block)
            if flow:
                # sendall only queues bytes on the PC. Do not queue the next
                # segment until this one has actually been acknowledged.
                flow.wait()
            chunk_index += 1
            streamed.update(block)
            if audit and (chunk_index <= 2 or bytes_sent >= next_checkpoint or bytes_sent == size):
                audit.event("chunk_sent", chunk=chunk_index,
                            chunk_bytes=len(block), bytes_sent=bytes_sent,
                            total_bytes=size,
                            tcp_acknowledged=bool(flow and flow.mode == "tcp-ack"),
                            send_ms=round((time.monotonic() - send_started) * 1000))
                if bytes_sent >= next_checkpoint:
                    next_checkpoint = bytes_sent + 64 * 1024
        if streamed.digest() != checksum:
            raise MailboxError(f"O arquivo {console} mudou durante o envio.")
        if audit:
            audit.event("transfer_stream_sent", bytes_sent=bytes_sent,
                        total_bytes=size, sha256=streamed.hexdigest())
    except (MailboxError, OSError, ValueError) as error:
        if audit:
            audit.event("transfer_failed", bytes_sent=locals().get("bytes_sent", 0),
                        total_bytes=size, error=str(error))
        raise
    finally:
        source.close()
        if flow:
            flow.close()
        sock.settimeout(previous_timeout)


def exact(sock, length):
    parts = bytearray()
    while len(parts) < length:
        block = sock.recv(min(4096, length - len(parts)))
        if not block:
            raise MailboxError("Conexao interrompida; copia incompleta nao registrada.")
        parts.extend(block)
    return bytes(parts)


def reply(sock, message="", ok=True):
    body = message.encode("utf-8")[:384]
    sock.sendall(struct.pack("<II", 0 if ok else 1, len(body)) + body)


def result(sock):
    status, length = struct.unpack("<II", exact(sock, 8))
    if status > 1 or length > 384:
        raise MailboxError("Resposta do console invalida.")
    text = exact(sock, length).decode("utf-8")
    if status:
        raise MailboxError(text)
    return text


def target_check(target, allow_unassigned=False):
    allowed = (0, 1, 2) if allow_unassigned else (1, 2)
    if type(target) is not int or target not in allowed:
        raise MailboxError("Destino invalido: escolha DS ou 3DS.")


def offer_decode(data):
    boxes, occupied, generations, bank_bytes, names_bytes = struct.unpack("<5I", data[:20])
    return dict(boxes=boxes, occupied=occupied, generations=generations,
                bankBytes=bank_bytes, namesBytes=names_bytes, hash=data[20:].hex())


def offer_encode(offer):
    return struct.pack("<5I", *(offer[k] for k in
                               ("boxes", "occupied", "generations", "bankBytes", "namesBytes"))) + bytes.fromhex(offer["hash"])


def preflight(offer, target):
    # Target zero is a server-held copy whose recipient is intentionally
    # unset. Compatibility is checked when the PC later chooses DS or 3DS.
    target_check(target, allow_unassigned=True)
    numbers = ("boxes", "occupied", "generations", "bankBytes", "namesBytes")
    if (not isinstance(offer, dict) or set(offer) != {*numbers, "hash"} or
            any(type(offer[k]) is not int or not 0 <= offer[k] <= 0xffffffff for k in numbers) or
            not isinstance(offer["hash"], str)):
        raise MailboxError("Metadados da oferta invalidos.")
    mask = 0x7f if target == 1 else 0x1ff
    if not (1 <= offer["boxes"] <= MAX_BOXES):
        raise MailboxError("Quantidade de boxes invalida.")
    if (offer["bankBytes"] != 16 + BOX_BYTES * offer["boxes"] or
            not 1 <= offer["namesBytes"] <= MAX_NAMES or
            offer["occupied"] > 30 * offer["boxes"] or
            offer["generations"] & ~mask):
        raise MailboxError("Tamanho ou geracoes incompativeis com o destino.")
    if not re.fullmatch(r"[0-9a-f]{64}", offer["hash"]):
        raise MailboxError("Hash invalido.")


def packet_id(target, digest):
    return hashlib.sha256(struct.pack("<I", target) + bytes.fromhex(digest)).hexdigest()[:32]


def no_duplicates(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise MailboxError("JSON com chaves duplicadas.")
        obj[key] = value
    return obj


def watch_for_source_updates(paths, marker, stop_event, on_update,
                            poll_interval=1.0, stable_checks=3):
    """Restart only after installed Python sources settle outside an update."""
    paths = tuple(Path(path) for path in paths)

    def signature():
        try:
            return tuple((str(path), hashlib.sha256(path.read_bytes()).digest())
                         for path in paths)
        except OSError:
            # A staged replacement may briefly remove a file. Wait for it.
            return None

    original = signature()
    candidate = None
    stable = 0
    while not stop_event.wait(poll_interval):
        if Path(marker).exists():
            candidate, stable = None, 0
            continue
        current = signature()
        if current is None:
            candidate, stable = None, 0
            continue
        if current == original:
            candidate, stable = None, 0
            continue
        if current == candidate:
            stable += 1
        else:
            candidate, stable = current, 1
        if stable >= stable_checks:
            on_update()
            return


def json_read(path):
    return json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=no_duplicates)


def sync_dir(path):
    # Windows has no portable directory-fsync in the standard library.
    # Files are still flushed before the atomic publication via os.replace.
    if os.name == "posix":
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try:
            os.fsync(fd)
        finally:
            os.close(fd)


def json_write_new(path, data):
    with path.open("xb") as stream:
        stream.write(json.dumps(data, ensure_ascii=True, separators=(",", ":")).encode("utf-8"))
        stream.flush()
        os.fsync(stream.fileno())


def atomic_json(path, data):
    temp = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        json_write_new(temp, data)
        os.replace(temp, path)
        sync_dir(path.parent)
    finally:
        temp.unlink(missing_ok=True)


def validate_package(folder, offer, target):
    preflight(offer, target)
    bank, names = folder / "bank.bnk", folder / "names.json"
    if bank.stat().st_size != offer["bankBytes"] or names.stat().st_size != offer["namesBytes"]:
        raise MailboxError("Tamanho gravado difere da oferta.")
    sha = hashlib.sha256()
    occupied = generations = 0
    with bank.open("rb") as stream:
        header = stream.read(16)
        if header != b"PKSMBANK" + struct.pack("<II", 3, offer["boxes"]):
            raise MailboxError("Cabecalho do banco invalido.")
        sha.update(header)
        for _ in range(offer["boxes"] * 30):
            entry = stream.read(ENTRY)
            if len(entry) != ENTRY:
                raise MailboxError("Banco incompleto.")
            sha.update(entry)
            gen = struct.unpack("<I", entry[:4])[0]
            if gen == 0xffffffff:
                continue
            if gen > 8:
                raise MailboxError("Geracao desconhecida no banco.")
            occupied += 1
            generations |= 1 << gen
    data = names.read_bytes()
    sha.update(data)
    if sha.hexdigest() != offer["hash"]:
        raise MailboxError("SHA-256 diferente; nenhum pacote registrado.")
    # Exporters emit an array of strings with no optional trailing NUL.
    labels = json.loads(data.decode("utf-8"), object_pairs_hook=no_duplicates)
    if (not isinstance(labels, list) or len(labels) != offer["boxes"] or
            any(not isinstance(s, str) or len(s.encode("utf-8")) > 512 for s in labels)):
        raise MailboxError("Nomes de boxes invalidos.")
    if occupied != offer["occupied"] or generations != offer["generations"]:
        raise MailboxError("Conteudo difere da descricao recebida.")


class DataLock:
    """Only one server process may write a data directory at a time."""
    def __init__(self, root):
        self.stream = (root / "server.lock").open("a+b")
        try:
            if os.name == "nt":
                import msvcrt
                self.stream.seek(0)
                if not self.stream.read(1):
                    self.stream.write(b"0")
                    self.stream.flush()
                self.stream.seek(0)
                msvcrt.locking(self.stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except (OSError, ImportError):
            self.stream.close()
            raise MailboxError("Ja existe um servidor usando esta pasta de dados.") from None

    def close(self):
        if self.stream.closed:
            return
        if os.name == "nt":
            import msvcrt
            self.stream.seek(0)
            msvcrt.locking(self.stream.fileno(), msvcrt.LK_UNLCK, 1)
        self.stream.close()


class Mailbox:
    def __init__(self, root, pin=None, max_bytes=512 * 1024 * 1024, max_items=1000):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.process_lock = DataLock(self.root)
        try:
            self.items = self.root / "items"
            self.temp = self.root / "incoming"
            self.items.mkdir(exist_ok=True)
            self.temp.mkdir(exist_ok=True)
            # Unpublished uploads belong only to this app. Keep published copies.
            for path in self.temp.iterdir():
                if path.is_dir() and not path.is_symlink():
                    shutil.rmtree(path)
                else:
                    path.unlink()
            config = self.root / "config.json"
            saved = json_read(config) if pin is None and config.exists() else None
            if pin is None and config.exists() and (not isinstance(saved, dict) or "pin" not in saved):
                raise MailboxError("Config do PC invalida; preserve a pasta de dados.")
            self.pin = pin if pin is not None else (saved["pin"] if saved is not None else secrets.randbelow(1000000))
            if type(self.pin) is not int or not 0 <= self.pin <= 999999:
                raise MailboxError("PIN invalido; use seis digitos.")
            if not config.exists() or pin is not None:
                atomic_json(config, {"pin": self.pin})
            self.lock = threading.RLock()
            self.delivery_lock = threading.RLock()
            self.on_stored = None
            self.max_bytes, self.max_items = max_bytes, max_items
            self.reserved_bytes = self.reserved_items = 0
            # Refuse damaged metadata, leaving it in place for recovery.
            for folder in self.items.iterdir():
                if folder.is_dir() and ID_RE.fullmatch(folder.name):
                    self.metadata(folder.name)
        except BaseException:
            self.process_lock.close()
            raise

    def close(self):
        self.process_lock.close()

    def metadata(self, item_id):
        if not ID_RE.fullmatch(item_id):
            raise MailboxError("Identificador invalido.")
        folder = self.items / item_id
        try:
            meta = json_read(folder / "meta.json")
            if meta["id"] != item_id or type(meta["delivered"]) is not int or meta["delivered"] not in (0, 1):
                raise MailboxError("Metadados da copia invalidos.")
            # Older packages predate this field and remain active in the queue.
            meta.setdefault("queue_cleared", 0)
            if type(meta["queue_cleared"]) is not int or meta["queue_cleared"] not in (0, 1):
                raise MailboxError("Estado da fila invalido.")
            preflight(meta["offer"], meta["target"])
            if packet_id(meta["target"], meta["offer"]["hash"]) != item_id:
                raise MailboxError("Identificador difere do hash gravado.")
            if not isinstance(meta["label"], str) or len(meta["label"].encode("utf-8")) > 63:
                raise MailboxError("Rotulo da copia invalido.")
            if type(meta["created"]) is not int or not 0 <= meta["created"] <= 0xffffffff:
                raise MailboxError("Data da copia invalida.")
            return meta
        except FileNotFoundError:
            raise MailboxError("Copia nao encontrada no PC.") from None
        except (KeyError, TypeError, ValueError):
            raise MailboxError("Metadados danificados; preserve a pasta de dados.") from None

    def all_metadata(self):
        return [self.metadata(p.name) for p in self.items.iterdir()
                if p.is_dir() and ID_RE.fullmatch(p.name)]

    def clear_pending(self):
        """Remove pending routes from the queue while retaining server backups."""
        with self.delivery_lock, self.lock:
            rows = self.all_metadata()
            pending = [meta for meta in rows
                       if meta["target"] in (1, 2) and not meta["delivered"]
                       and not meta["queue_cleared"]]
            for meta in pending:
                meta["queue_cleared"] = 1
                atomic_json(self.items / meta["id"] / "meta.json", meta)
            return [meta["id"] for meta in pending]

    def notify_stored(self, folder, offer):
        if self.on_stored is not None:
            self.on_stored(folder, offer)

    @contextlib.contextmanager
    def reserve(self, size):
        with self.lock:
            metas = self.all_metadata()
            used = sum(m["offer"]["bankBytes"] + m["offer"]["namesBytes"] for m in metas)
            if (used + self.reserved_bytes + size > self.max_bytes or
                    len(metas) + self.reserved_items >= self.max_items):
                raise MailboxError("Caixa postal cheia. Aumente o limite no PC.")
            if shutil.disk_usage(self.root).free < size + self.reserved_bytes + 1024 * 1024:
                raise MailboxError("Espaco livre insuficiente no PC.")
            self.reserved_bytes += size
            self.reserved_items += 1
        try:
            yield
        finally:
            with self.lock:
                self.reserved_bytes -= size
                self.reserved_items -= 1

    def upload(self, sock):
        target, label_size = struct.unpack("<II", exact(sock, 8))
        target_check(target, allow_unassigned=True)
        if not 1 <= label_size <= 63:
            raise MailboxError("Rotulo do banco invalido.")
        label = exact(sock, label_size).decode("utf-8")
        if any(ord(c) < 32 or ord(c) == 127 for c in label):
            raise MailboxError("Rotulo contem caracteres de controle.")
        offer = offer_decode(exact(sock, 52))
        preflight(offer, target)
        item_id = packet_id(target, offer["hash"])
        final = self.items / item_id
        with self.lock:
            if final.exists():
                meta = self.metadata(item_id)
                if meta["offer"] != offer:
                    raise MailboxError("Descricao difere da copia ja guardada.")
                validate_package(final, offer, target)
                existing = True
            else:
                existing = False
        if existing:
            self.notify_stored(final, offer)
            reply(sock, "STORED " + item_id)
            return
        with self.reserve(offer["bankBytes"] + offer["namesBytes"]):
            temp = self.temp / uuid.uuid4().hex
            temp.mkdir()
            try:
                reply(sock, "READY")
                for name, size in (("bank.bnk", offer["bankBytes"]), ("names.json", offer["namesBytes"])):
                    with (temp / name).open("xb") as stream:
                        remaining = size
                        while remaining:
                            data = exact(sock, min(4096, remaining))
                            stream.write(data)
                            remaining -= len(data)
                        stream.flush()
                        os.fsync(stream.fileno())
                validate_package(temp, offer, target)
                meta = dict(id=item_id, target=target, label=label, offer=offer,
                            created=int(time.time()), delivered=0, queue_cleared=0)
                json_write_new(temp / "meta.json", meta)
                sync_dir(temp)
                with self.lock:
                    if final.exists():
                        other = self.metadata(item_id)
                        if other["offer"] != offer:
                            raise MailboxError("Descricao difere da copia existente.")
                        validate_package(final, offer, target)
                    else:
                        os.rename(temp, final)
                        sync_dir(self.items)
                        sync_dir(self.temp)
                self.notify_stored(final, offer)
                reply(sock, item_id)
                destination = {0: "PC, sem destinatario", 1: "DS", 2: "3DS"}[target]
                LOG.info("Guardado para %s: %s (%d boxes), ID %s", destination, label, offer["boxes"], item_id[:8])
            finally:
                if temp.exists():
                    shutil.rmtree(temp)

    def listing(self, sock):
        target, include_delivered, offset = struct.unpack("<III", exact(sock, 12))
        if target:
            target_check(target)
        if include_delivered > 1 or offset > 10000 or (not target and not include_delivered):
            raise MailboxError("Pedido de lista invalido.")
        with self.lock:
            rows = sorted((m for m in self.all_metadata() if (not target or m["target"] == target) and
                           not m["queue_cleared"] and
                           (include_delivered or not m["delivered"])), key=lambda m: (m["created"], m["id"]))
            subset = rows[offset:offset + PAGE_SIZE]
            items = [dict(id=m["id"], target=m["target"], label=m["label"], delivered=m["delivered"], **m["offer"]) for m in subset]
            data = dict(items=items, total=len(rows), next=offset + PAGE_SIZE if offset + PAGE_SIZE < len(rows) else 0)
        body = json.dumps(data, ensure_ascii=True, separators=(",", ":")).encode("utf-8")
        reply(sock)
        sock.sendall(struct.pack("<I", len(body)) + body)

    def fetch(self, sock):
        # Keep an active console delivery from losing its files while the PC
        # user clears the pending queue.
        with self.delivery_lock:
            return self._fetch_locked(sock)

    def _fetch_locked(self, sock):
        target = struct.unpack("<I", exact(sock, 4))[0]
        target_check(target)
        item_id = exact(sock, 32).decode("ascii")
        flags = struct.unpack("<I", exact(sock, 4))[0]
        if flags > 1:
            raise MailboxError("Opcoes de recebimento invalidas.")
        with self.lock:
            meta = self.metadata(item_id)
            if meta["queue_cleared"]:
                raise MailboxError("Esta copia foi retirada da fila. Reenvie-a pelo PC para disponibiliza-la ao console.")
            if target != meta["target"]:
                raise MailboxError("Esta copia pertence ao outro console.")
        folder = self.items / item_id
        validate_package(folder, meta["offer"], target)
        reply(sock)
        sock.sendall(offer_encode(meta["offer"]))
        if result(sock) != "READY":
            raise MailboxError("Console nao confirmou recebimento.")
        for name in ("bank.bnk", "names.json"):
            with (folder / name).open("rb") as stream:
                while True:
                    data = stream.read(4096)
                    if not data:
                        break
                    sock.sendall(data)
        bank = result(sock)
        while bank == "VERIFY":
            bank = result(sock)
        if not re.fullmatch(r"link[0-9]{4}", bank):
            raise MailboxError("Confirmacao do banco invalida.")
        if flags == 0:
            with self.lock:
                meta = self.metadata(item_id)
                meta["delivered"] = 1
                atomic_json(folder / "meta.json", meta)
        reply(sock, "DELIVERED" if flags == 0 else "BACKUP")
        LOG.info("%s: ID %s, banco %s. Copia mantida no PC.",
                 ("Entregue a " + ("DS" if target == 1 else "3DS")) if flags == 0 else "Backup recuperado; fila do destinatario mantida",
                 item_id[:8], bank)


class Handler(socketserver.BaseRequestHandler):
    def handle(self):
        sock, server = self.request, self.server
        sock.settimeout(server.timeout_seconds)
        audit = None
        peer_registered = False
        try:
            magic, version, pin, command = struct.unpack("<8sIII", exact(sock, 20))
            if command in (4, 5):
                console = "3DS" if command == 4 else "DS"
                audit = UpdateAudit(server, self.client_address[0], console)
                audit.event("client_hello_received", protocol_version=version,
                            protocol_magic_valid=(magic == b"CLMAIL01"))
            if magic != b"CLMAIL01" or version != 1 or pin != server.mailbox.pin:
                if audit:
                    audit.event("authentication_rejected",
                                reason="protocol_mismatch" if magic != b"CLMAIL01" or version != 1 else "pin_mismatch")
                raise MailboxError("PIN incorreto ou protocolo incompativel.")
            if command not in (1, 2, 3, 4, 5):
                raise MailboxError("Comando desconhecido.")
            if audit:
                audit.event("authentication_accepted")
                server.register_update_peer(self.client_address[0], audit)
                peer_registered = True
            reply(sock)
            if audit:
                audit.event("server_hello_ack_sent")
            if command in (4, 5):
                try:
                    image, version = server.update_for(command)
                    serve_update(sock, image, version, console, audit)
                except (MailboxError, OSError, ValueError) as exc:
                    audit.event("update_failed", error=str(exc))
                    LOG.warning("%s: atualizacao %s: %s", self.client_address[0], console, exc)
                return
            {1: server.mailbox.upload, 2: server.mailbox.listing, 3: server.mailbox.fetch}[command](sock)
        except (MailboxError, OSError, ValueError, RecursionError) as exc:
            if audit:
                audit.event("session_failed", error=str(exc))
            LOG.warning("%s: %s", self.client_address[0], exc)
            try:
                reply(sock, str(exc), ok=False)
            except OSError:
                pass
        finally:
            if peer_registered:
                server.unregister_update_peer(self.client_address[0], audit)
            if audit:
                audit.event("session_closed")


class Server(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    # Wait for active transactions during shutdown; bodies time out normally.
    daemon_threads = False

    def __init__(self, address, mailbox, timeout_seconds=180,
                 update_path=None, update_version=0,
                 nds_update_path=None, nds_update_version=0):
        self.mailbox = mailbox
        self.timeout_seconds = timeout_seconds
        self.update_path = Path(update_path) if update_path else None
        self.update_version = update_version
        self.nds_update_path = Path(nds_update_path) if nds_update_path else None
        self.nds_update_version = nds_update_version
        self.update_log_path = self.mailbox.root / "update-communication.jsonl"
        self.update_log_lock = threading.Lock()
        self.update_peer_lock = threading.Lock()
        self.update_peer_audits = {}
        self.recent_update_peers = {}
        self.active_lock = threading.Lock()
        self.active = set()
        self.closing = False
        super().__init__(address, Handler)

    def register_update_peer(self, peer_ip, audit):
        with self.update_peer_lock:
            self.update_peer_audits.setdefault(peer_ip, []).append(audit)

    def unregister_update_peer(self, peer_ip, audit):
        with self.update_peer_lock:
            audits = self.update_peer_audits.get(peer_ip, [])
            if audit in audits:
                audits.remove(audit)
            if not audits:
                self.update_peer_audits.pop(peer_ip, None)
            # A console learns about a dropped TCP stream only after the PC
            # has closed it. Keep the authenticated peer association briefly
            # so its final failure/radio counters can arrive over UDP.
            self.recent_update_peers[peer_ip] = (
                audit, time.monotonic() + UPDATE_SOCKET_TIMEOUT_SECONDS + 30)
            now = time.monotonic()
            for address, (_, expires) in list(self.recent_update_peers.items()):
                if expires <= now:
                    self.recent_update_peers.pop(address, None)
            while len(self.recent_update_peers) > 64:
                self.recent_update_peers.pop(next(iter(self.recent_update_peers)))

    def record_update_telemetry(self, peer_ip, payload):
        with self.update_peer_lock:
            audits = self.update_peer_audits.get(peer_ip, [])
            audit = audits[-1] if audits else None
            if audit is None:
                recent = self.recent_update_peers.get(peer_ip)
                if recent:
                    candidate, expires = recent
                    if expires > time.monotonic():
                        audit = candidate
                    else:
                        self.recent_update_peers.pop(peer_ip, None)
        if audit is None or not 1 <= len(payload) <= 1100:
            return
        try:
            client = json.loads(payload.decode("utf-8"))
            if not isinstance(client, dict):
                return
            client_session = client.get("session")
            event = client.get("event")
            if (not isinstance(client_session, str) or
                    not re.fullmatch(r"[A-Za-z0-9-]{1,48}", client_session) or
                    not isinstance(event, str) or not re.fullmatch(r"[a-z_]{1,48}", event)):
                return
            allowed = {
                "elapsed_ms", "phase", "tcp_sent_bytes", "tcp_received_bytes",
                "udp_logs_sent", "udp_logs_failed", "local_log_open", "radio",
                "idle_ms",
                "name", "server_ip",
                "server_port", "timeout_ms", "error", "current_version",
                "offered_version", "file_bytes", "destination", "bytes_written",
                "total_bytes", "state", "version",
            }
            details = {}
            for key in allowed & client.keys():
                value = client[key]
                if isinstance(value, str):
                    details[key] = value[:500]
                elif type(value) is int and 0 <= value <= 0xffffffff:
                    details[key] = value
            record = {
                "time": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "server_session": audit.session,
                "client_session": client_session,
                "peer_ip": peer_ip,
                "console": audit.console,
                "transport": "udp-client-trace",
                "event": event,
            }
            record.update(details)
            encoded = json.dumps(record, ensure_ascii=True, sort_keys=True) + "\n"
            with self.update_log_lock, self.update_log_path.open("a", encoding="utf-8") as stream:
                stream.write(encoded)
                stream.flush()
        except (UnicodeError, ValueError, OSError):
            return

    def update_for(self, command):
        if command == 4:
            if self.update_path:
                return self.update_path, self.update_version
            return find_3ds_update()
        if command == 5:
            if self.nds_update_path:
                return self.nds_update_path, self.nds_update_version
            return find_nds_update()
        raise ValueError("Comando de atualizacao invalido.")

    def process_request(self, request, address):
        with self.active_lock:
            if self.closing or len(self.active) >= 16:
                request.close()
                return
            self.active.add(request)
        try:
            super().process_request(request, address)
        except BaseException:
            with self.active_lock:
                self.active.discard(request)
            request.close()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request, address)
        finally:
            with self.active_lock:
                self.active.discard(request)

    def server_close(self):
        with self.active_lock:
            self.closing = True
            for request in self.active:
                try:
                    request.shutdown(socket.SHUT_RDWR)
                except OSError:
                    pass
        super().server_close()


def local_ips(bind):
    if bind != "0.0.0.0":
        return [bind]
    addresses = set()
    try:
        addresses.update(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass
    try:
        # UDP connect selects the local interface; it does not send a packet.
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("192.0.2.1", 9))
            addresses.add(probe.getsockname()[0])
    except OSError:
        pass
    return sorted(ip for ip in addresses if not ip.startswith("127.") and ip != "0.0.0.0")


def main():
    parser = argparse.ArgumentParser(description="Secretaria de boxes Chest Link (DS <-> PC <-> 3DS)")
    parser.add_argument("--data", type=Path, default=Path(__file__).resolve().parent / "dados",
                        help="pasta persistente de copias; padrao: dados ao lado do servidor")
    parser.add_argument("--bind", default="0.0.0.0", help="IPv4 local de escuta")
    parser.add_argument("--port", type=int, default=PORT, help="porta TCP; consoles usam 40992")
    parser.add_argument("--pin", type=int, help="PIN de 0 a 999999; gerado e salvo no primeiro uso")
    parser.add_argument("--max-mib", type=int, default=512, help="limite dos bancos guardados (MiB)")
    parser.add_argument("--max-items", type=int, default=1000, help="limite de copias, ate 10000")
    parser.add_argument("--no-ui", action="store_true", help="somente servidor TCP, sem interface grafica")
    parser.add_argument("--no-browser", action="store_true", help="inicia a interface sem abrir o navegador")
    parser.add_argument("--web-port", type=int, default=8765, help="porta da interface web; 0 escolhe uma livre")
    parser.add_argument("--web-bind", default="0.0.0.0",
                        help="IPv4 de escuta da interface web; 0.0.0.0 permite acesso pela rede local")
    args = parser.parse_args()
    if not 1 <= args.max_items <= 10000 or args.max_mib < 1 or not 1 <= args.port <= 65535 or not 0 <= args.web_port <= 65535:
        parser.error("Limites ou porta invalidos.")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    mailbox = None
    hotspot = None
    restart_requested = threading.Event()
    watch_stop = threading.Event()
    watcher = None
    discovery = None
    try:
        mailbox = Mailbox(args.data, args.pin, args.max_mib * 1024 * 1024, args.max_items)
        if __package__:
            from .ds_hotspot import DSHotspot
        else:
            from ds_hotspot import DSHotspot
        hotspot = DSHotspot(args.port, args.bind)
        update_path, update_version = find_3ds_update()
        nds_update_path, nds_update_version = find_nds_update()
        with Server((args.bind, args.port), mailbox) as server:
            try:
                discovery = DiscoveryResponder(
                    (server.server_address[0], server.server_address[1]),
                    server=server).start()
            except OSError as exc:
                print(f"Descoberta automatica do DS indisponivel: {exc}", flush=True)
            metas = mailbox.all_metadata()
            print("\nCHEST LINK - SERVIDOR DO PC", flush=True)
            addresses = local_ips(args.bind)
            print("IP do PC: " + (" / ".join(addresses) or "consulte ipconfig ou ip addr no PC"))
            print(f"PIN: {mailbox.pin:06d}    Porta TCP: {args.port}")
            print(f"Dados: {mailbox.root}")
            print(f"Log de atualizacoes: {mailbox.root / 'update-communication.jsonl'}")
            print("Atualizacao DS: " + (f"v{nds_update_version >> 16}.{(nds_update_version >> 8) & 255}.{nds_update_version & 255}"
                                        if nds_update_path else "indisponivel neste pacote"))
            print("Atualizacao 3DS: " + (f"v{update_version >> 16}.{(update_version >> 8) & 255}.{update_version & 255}"
                                        if update_path else "indisponivel neste pacote"))
            print(f"Pendentes DS: {sum(m['target'] == 1 and not m['delivered'] and not m['queue_cleared'] for m in metas)}; "
                  f"3DS: {sum(m['target'] == 2 and not m['delivered'] and not m['queue_cleared'] for m in metas)}")
            print("Nos consoles: Enviar ao PC guarda uma fila; o PC pode enviar diretamente ao listener. Ctrl+C encerra.\n", flush=True)
            ui = None
            try:
                if not args.no_ui:
                    try:
                        if __package__:
                            from .interface import Interface
                        else:
                            from interface import Interface
                        web_addresses = local_ips(args.web_bind)
                        ui = Interface(sys.modules[__name__], mailbox, server.server_address,
                                       addresses, args.web_port, args.web_bind, web_addresses,
                                       hotspot=hotspot)
                        ui.start(not args.no_browser)
                        print("Interface de boxes neste PC: " + ui.url, flush=True)
                        if ui.network_urls:
                            print("Acesso pela rede local (abre um destes links no outro computador): " +
                                  " / ".join(ui.network_urls), flush=True)
                    except (ImportError, OSError, ValueError) as exc:
                        if ui:
                            ui.close()
                        ui = None
                        if hotspot:
                            try:
                                hotspot.close()
                            except RuntimeError as cleanup_error:
                                print(f"Rede DS precisa de limpeza manual: {cleanup_error}", flush=True)
                        print(f"Interface indisponivel: {exc}. Servidor TCP continua funcionando.", flush=True)
                script = Path(__file__).resolve()

                def request_restart():
                    print("Atualizacao do servidor instalada; reiniciando e preservando os dados...", flush=True)
                    restart_requested.set()
                    server.shutdown()

                watcher = threading.Thread(
                    target=watch_for_source_updates,
                    args=((script, script.with_name("interface.py"), script.with_name("native_saves.py"),
                           script.with_name("pokemon.py"),
                           script.with_name("ds_hotspot.py")),
                          script.parent / ".chest-link-update-in-progress", watch_stop,
                          request_restart),
                    name="chest-link-update-watcher", daemon=True)
                watcher.start()
                server.serve_forever(poll_interval=0.25)
            finally:
                watch_stop.set()
                if discovery:
                    discovery.close()
                if ui:
                    ui.close()
                if watcher:
                    watcher.join(timeout=2)
    except KeyboardInterrupt:
        print("\nServidor encerrado. As copias permanecem na pasta de dados.")
    except (OSError, MailboxError, ValueError) as exc:
        print(f"Nao foi possivel iniciar: {exc}")
        return 1
    finally:
        if mailbox:
            mailbox.close()
    if restart_requested.is_set():
        os.execv(sys.executable, [sys.executable, *sys.argv])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
