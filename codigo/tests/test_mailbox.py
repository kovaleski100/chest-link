"""Real TCP tests: Python PC server <-> the C++ code used on DS/3DS."""
import hashlib
import json
import logging
import os
from pathlib import Path
import socket
import struct
import subprocess
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from server import chest_link_server as pc

ROOT = Path(__file__).resolve().parents[1]
CLI = Path(os.environ.get("CHEST_LINK_CLI", ROOT / "build/chest-link-cli"))
PROBE = Path(os.environ.get("CHEST_LINK_PROBE", ROOT / "build/mailbox-probe"))
UPDATE_PROBE = Path(os.environ.get("CHEST_LINK_UPDATE_PROBE", ROOT / "build/update-probe"))
DISCOVERY_PROBE = Path(os.environ.get("CHEST_LINK_DISCOVERY_PROBE", ROOT / "build/discovery-probe"))
PIN = 123456
logging.getLogger("chest-link").setLevel(logging.CRITICAL)


class DSUpdateFlowTests(unittest.TestCase):
    class RadioSocket:
        """A receiver whose current frame is lost if the sender queues another.

        TCP_INFO first reports queued bytes, then a segment awaiting ACK, then
        delivery. This models the NTR limitation without claiming radio tests.
        """
        family = socket.AF_INET

        def __init__(self, stalled=False, tcp_info=True):
            self.timeout = 2
            self.nodelay = 0
            self.started = False
            self.pending = 0
            self.polls = 0
            self.stalled = stalled
            self.tcp_info = tcp_info
            self.sent = []
            self.clock = 0
            self.events = []

        def event(self, name, **fields):
            self.events.append(dict(event=name, **fields))

        def gettimeout(self):
            return self.timeout

        def settimeout(self, timeout):
            self.timeout = timeout

        def getsockopt(self, level, option, size=None):
            if option == socket.TCP_NODELAY:
                return self.nodelay
            if not self.tcp_info:
                raise OSError("unsupported")
            info = bytearray(192)
            info[0] = 1
            struct.pack_into("=I", info, 16, 536)  # Smaller than the default 1 KiB.
            if self.pending:
                self.polls += 1
                if self.polls == 1:
                    struct.pack_into("=I", info, 144, self.pending)
                elif self.stalled or self.polls < 4:
                    struct.pack_into("=I", info, 24, 1)
                else:
                    self.pending = 0
            return bytes(info)

        def setsockopt(self, level, option, value):
            self.nodelay = value

        def sendall(self, data):
            if self.started and self.tcp_info and self.nodelay:
                if self.pending:
                    raise AssertionError("next frame overwrote unacknowledged data")
                if len(data) > 536:
                    raise AssertionError("one write generated multiple TCP segments")
                self.pending, self.polls = len(data), 0
            self.sent.append(bytes(data))

        def recv(self, length):
            self.started = True
            return struct.pack("<I", 1)[:length]

        def sleep(self, seconds):
            self.clock += seconds

    def stream(self, sock, console="DS"):
        with tempfile.TemporaryDirectory(prefix="ds-flow-") as area:
            image = Path(area) / "app.nds"
            payload = bytes(range(251)) * 9
            image.write_bytes(payload)
            with patch.object(pc.time, "monotonic", side_effect=lambda: sock.clock), \
                    patch.object(pc.time, "sleep", side_effect=sock.sleep), \
                    patch.object(pc.sys, "platform", "linux"), \
                    patch.object(pc.socket, "TCP_INFO", 11, create=True):
                pc.serve_update(sock, image, 0x509, console, sock)
            return payload

    def test_waits_for_ack_and_unsent_queue_before_sending_next_segment(self):
        sock = self.RadioSocket()
        payload = self.stream(sock)
        self.assertEqual(b"".join(sock.sent)[64:], payload)  # No hello in serve_update.
        manifest = sock.sent[1]
        self.assertEqual(manifest[16:], hashlib.sha256(payload).digest())
        flow = next(e for e in sock.events if e["event"] == "transfer_flow_control")
        self.assertEqual((flow["mode"], flow["chunk_bytes"]), ("tcp-ack", 536))
        self.assertGreater(sock.clock, 0)
        self.assertTrue(all(e["tcp_acknowledged"] for e in sock.events
                            if e["event"] == "chunk_sent"))
        self.assertEqual((sock.nodelay, sock.timeout), (0, 2))

    def test_stalled_ack_stops_before_queueing_file_data(self):
        sock = self.RadioSocket(stalled=True)
        with patch.object(pc, "DS_UPDATE_ACK_TIMEOUT_SECONDS", 0.02):
            with self.assertRaises(pc.MailboxError):
                self.stream(sock)
        self.assertEqual(len(sock.sent), 3)  # Availability, manifest, start reply.
        self.assertIn("tcp_ack_timeout", [e["event"] for e in sock.events])
        self.assertIn("transfer_failed", [e["event"] for e in sock.events])
        self.assertEqual((sock.nodelay, sock.timeout), (0, 2))

    def test_portable_fallback_paces_small_blocks_and_does_not_claim_tcp_acks(self):
        sock = self.RadioSocket(tcp_info=False)
        payload = self.stream(sock)
        self.assertEqual(b"".join(sock.sent)[64:], payload)
        self.assertTrue(all(len(block) <= 256 for block in sock.sent[3:]))
        self.assertAlmostEqual(sock.clock, (len(sock.sent) - 2) * pc.DS_UPDATE_PACE_SECONDS)
        self.assertTrue(all(not e["tcp_acknowledged"] for e in sock.events
                            if e["event"] == "chunk_sent"))

    def test_3ds_keeps_native_streaming(self):
        sock = self.RadioSocket()
        payload = self.stream(sock, "3DS")
        self.assertEqual(sock.sent[3:], [payload])
        self.assertEqual(sock.clock, 0)
        self.assertNotIn("transfer_flow_control", [e["event"] for e in sock.events])


class MailboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="chest-mailbox-")
        self.root = Path(self.temp.name)
        self.src, self.dst = self.root / "source", self.root / "destination"
        self.create_bank(self.src, 3)
        self.dst.mkdir()
        self.update_data = (bytes(range(256)) * 513)[:131077]
        self.update_path = self.root / "release.3dsx"
        self.update_path.write_bytes(self.update_data)
        self.nds_update_data = (bytes(range(251)) * 1400)[:310001]
        self.nds_update_path = self.root / "release.nds"
        self.nds_update_path.write_bytes(self.nds_update_data)
        self.original = self.snapshot(self.src)
        self.start_server()

    def start_server(self):
        self.box = pc.Mailbox(self.root / "pc", PIN)
        self.server = pc.Server(("127.0.0.1", 0), self.box, timeout_seconds=2,
                                update_path=self.update_path, update_version=0x403,
                                nds_update_path=self.nds_update_path,
                                nds_update_version=0x403)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01})
        self.thread.start()

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.box.close()

    def tearDown(self):
        self.stop_server()
        self.assertEqual(self.original, self.snapshot(self.src))
        self.temp.cleanup()

    @staticmethod
    def create_bank(root, boxes, gen=0):
        (root / "banks").mkdir(parents=True, exist_ok=True)
        data = bytearray(b"PKSMBANK" + struct.pack("<II", 3, boxes))
        for box in range(boxes):
            for slot in range(30):
                entry = bytearray([0xff] * 336)
                if slot < 2:
                    entry[:4] = struct.pack("<I", gen)
                    entry[4:332] = bytes([(box + slot) % 256]) * 328
                data.extend(entry)
        (root / "banks/test.bnk").write_bytes(data)
        (root / "banks/test.json").write_text(json.dumps([f"Box {i + 1}" for i in range(boxes)]))
        (root / "banks.json").write_text(json.dumps({"test": boxes}))

    @staticmethod
    def snapshot(root):
        return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*")
                if p.is_file() and "chest-link" not in p.parts}

    def cli(self, *args, ok=True):
        run = subprocess.run([str(CLI), *map(str, args)], text=True, capture_output=True, timeout=30)
        if ok:
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        else:
            self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
        return run.stdout + run.stderr

    def upload(self, target=2, selection="1,3", root=None):
        text = self.cli("mail-send", root or self.src, "test", selection, "127.0.0.1", PIN, target, self.port)
        return text.strip().split()[-1]

    def listing(self, target=2, include=0, offset=0):
        text = self.cli("mail-list", self.dst, "127.0.0.1", PIN, target, include, offset, self.port)
        lines = text.splitlines()
        header = lines[0].split()
        return int(header[1]), int(header[2]), [s.split()[1] for s in lines[1:]]

    def fetch(self, item, target=2, max_boxes=500, ok=True):
        return self.cli("mail-fetch", self.dst, "127.0.0.1", PIN, target, item, self.port, max_boxes, ok=ok)

    def probe(self, item, fault, target=2, code=0):
        run = subprocess.run([str(PROBE), str(self.dst), "127.0.0.1", str(PIN), str(target), item,
                              str(self.port), fault], text=True, capture_output=True, timeout=30)
        self.assertEqual(run.returncode, code, run.stdout + run.stderr)
        return run.stdout + run.stderr

    def connection(self, command, pin=PIN):
        sock = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        sock.sendall(struct.pack("<8sIII", b"CLMAIL01", 1, pin, command))
        pc.result(sock)
        return sock

    def offered_package(self, target=2, mutate=None):
        bank = (self.src / "banks/test.bnk").read_bytes()
        names = json.dumps(["Box 1", "Box 2", "Box 3"], separators=(",", ":")).encode()
        offer = dict(boxes=3, occupied=6, generations=1, bankBytes=len(bank), namesBytes=len(names),
                     hash=hashlib.sha256(bank + names).hexdigest())
        if mutate:
            mutate(offer)
        sock = self.connection(1)
        sock.sendall(struct.pack("<II", target, 4) + b"Test" + pc.offer_encode(offer))
        return sock, offer, bank, names

    def wait_incoming_clean(self):
        deadline = time.monotonic() + 4
        while list(self.box.temp.iterdir()) and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(list(self.box.temp.iterdir()), [])

    def test_both_directions_and_box_byte_order(self):
        for target in (1, 2):
            item = self.upload(target)
            self.assertEqual(self.listing(target)[2], [item])
            text = self.fetch(item, target)
            self.assertIn("ACK 1", text)
            name = text.split()[1]
            actual = (self.dst / f"banks/{name}.bnk").read_bytes()
            original = (self.src / "banks/test.bnk").read_bytes()
            expected = b"PKSMBANK" + struct.pack("<II", 3, 2) + original[16:10096] + original[20176:30256]
            self.assertEqual(actual, expected)
            self.assertEqual(json.loads((self.dst / f"banks/{name}.json").read_text()), ["Box 1", "Box 3"])
            self.assertEqual(self.listing(target)[2], [])
            self.assertEqual(self.listing(target, 1)[2], [item])
            self.assertTrue((self.box.items / item / "bank.bnk").exists())

    def test_cleared_pending_copy_is_retained_but_hidden_from_console_until_requeued(self):
        item = self.upload()
        before = {name: (self.box.items / item / name).read_bytes()
                  for name in ("bank.bnk", "names.json")}
        self.assertEqual(self.box.clear_pending(), [item])
        self.assertEqual(self.listing(2)[2], [])
        self.assertEqual(self.listing(2, 1)[2], [])
        self.assertIn("Esta copia foi retirada da fila", self.fetch(item, ok=False))
        self.assertEqual(self.box.metadata(item)["queue_cleared"], 1)
        self.assertEqual(before, {name: (self.box.items / item / name).read_bytes()
                                  for name in before})
        self.assertEqual(self.box.clear_pending(), [])

    def test_source_update_watcher_waits_for_staged_install_to_finish(self):
        with tempfile.TemporaryDirectory(prefix="chest-update-watch-") as folder:
            root = Path(folder)
            source = root / "servidor.py"
            marker = root / ".chest-link-update-in-progress"
            source.write_text("version = 1")
            marker.touch()
            stopped = threading.Event()
            updated = threading.Event()
            watcher = threading.Thread(
                target=pc.watch_for_source_updates,
                args=((source,), marker, stopped, updated.set),
                kwargs={"poll_interval": 0.01, "stable_checks": 3})
            watcher.start()
            time.sleep(0.05)  # Let the watcher capture the pre-update version.
            source.write_text("version = 2")
            time.sleep(0.08)
            self.assertFalse(updated.is_set())
            marker.unlink()
            self.assertTrue(updated.wait(1))
            stopped.set()
            watcher.join(timeout=1)
            self.assertFalse(watcher.is_alive())

    def test_udp_discovery_echoes_nonce_and_ignores_malformed_requests(self):
        responder = pc.DiscoveryResponder(("127.0.0.1", 0)).start()
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as client:
                client.settimeout(0.25)
                client.sendto(b"NOTCHESTLINK", responder.address)
                with self.assertRaises(socket.timeout):
                    client.recvfrom(64)

                nonce = b"\x19\x42\xa7\xfe"
                client.sendto(pc.DISCOVERY_REQUEST + nonce, responder.address)
                response, _ = client.recvfrom(64)
                self.assertEqual(response, pc.DISCOVERY_RESPONSE + nonce)
        finally:
            responder.close()

    def test_update_telemetry_is_saved_only_for_an_authenticated_update_peer(self):
        audit = pc.UpdateAudit(self.server, "127.0.0.1", "DS")
        responder = pc.DiscoveryResponder(("127.0.0.1", 0), server=self.server).start()
        record = {
            "session": "987650-1", "event": "download_progress",
            "elapsed_ms": 2500, "phase": "download",
            "tcp_received_bytes": 65536, "bytes_written": "61440",
            "total_bytes": "1329664",
            "radio": "driver=NTR security=WPA2 ccmp_valid=48 mic_failed=0",
        }
        sender = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            deadline = time.monotonic() + 2
            log_path = self.box.root / "update-communication.jsonl"
            sender.sendto(pc.UPDATE_TRACE_MAGIC + json.dumps(record).encode(),
                          responder.address)
            time.sleep(0.05)
            self.assertNotIn("udp-client-trace", log_path.read_text())

            self.server.register_update_peer("127.0.0.1", audit)
            sender.sendto(pc.UPDATE_TRACE_MAGIC + json.dumps(record).encode(),
                          responder.address)
            while time.monotonic() < deadline:
                if log_path.is_file() and "udp-client-trace" in log_path.read_text():
                    break
                time.sleep(0.01)
            lines = [json.loads(line) for line in log_path.read_text().splitlines()]
            client_record = next(row for row in lines
                                 if row.get("transport") == "udp-client-trace")
            self.assertEqual(client_record["client_session"], "987650-1")
            self.assertEqual(client_record["event"], "download_progress")
            self.assertEqual(client_record["peer_ip"], "127.0.0.1")
            self.assertIn("security=WPA2", client_record["radio"])
            self.assertNotIn(str(PIN), log_path.read_text())

            # The console reports a TCP timeout only after the PC socket has
            # closed. Preserve the authenticated association briefly for that
            # final radio snapshot.
            self.server.unregister_update_peer("127.0.0.1", audit)
            record.update(event="update_failed", elapsed_ms=3100,
                          tcp_received_bytes=8192)
            sender.sendto(pc.UPDATE_TRACE_MAGIC + json.dumps(record).encode(),
                          responder.address)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                rows = [json.loads(line) for line in log_path.read_text().splitlines()]
                if any(row.get("transport") == "udp-client-trace" and
                       row.get("event") == "update_failed" for row in rows):
                    break
                time.sleep(0.01)
            self.assertTrue(any(row.get("transport") == "udp-client-trace" and
                                row.get("event") == "update_failed" and
                                row.get("tcp_received_bytes") == 8192
                                for row in rows))
        finally:
            sender.close()
            self.server.unregister_update_peer("127.0.0.1", audit)
            responder.close()

    def test_ds_udp_broadcast_discovers_server_address(self):
        responder = pc.DiscoveryResponder(("0.0.0.0", 0)).start()
        try:
            result = subprocess.run([str(DISCOVERY_PROBE), str(responder.address[1])],
                                    text=True, capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertRegex(result.stdout.strip(), r"^(?:\d{1,3}\.){3}\d{1,3}$")
        finally:
            responder.close()

    def test_pc_discovers_nds_release_only_when_manifest_matches_binary(self):
        with tempfile.TemporaryDirectory(prefix="chest-nds-release-") as folder:
            root = Path(folder)
            script = root / "PC" / "servidor.py"
            image = root / "DS" / "ChestLink_DS.nds"
            script.parent.mkdir()
            image.parent.mkdir()
            script.touch()
            image.write_bytes(self.nds_update_data)
            manifest = dict(format=1, version=0x403, size=len(self.nds_update_data),
                            sha256=hashlib.sha256(self.nds_update_data).hexdigest())
            image.with_name("release.json").write_text(json.dumps(manifest))
            with patch.object(pc, "__file__", str(script)):
                found, version = pc.find_nds_update()
            self.assertEqual(found, image)
            self.assertEqual(version, 0x403)

            manifest["sha256"] = "0" * 64
            image.with_name("release.json").write_text(json.dumps(manifest))
            with patch.object(pc, "__file__", str(script)):
                found, version = pc.find_nds_update()
            self.assertIsNone(found)
            self.assertEqual(version, 0)

    def test_unassigned_console_upload_waits_for_manual_pc_routing(self):
        item = self.upload(0)
        self.assertEqual(self.listing(0, 1)[2], [item])
        self.assertEqual(self.listing(1)[2], [])
        self.assertEqual(self.listing(2)[2], [])
        self.fetch(item, 2, ok=False)
        self.assertEqual(self.box.metadata(item)["target"], 0)

    def test_unassigned_upload_defers_generation_compatibility_until_destination(self):
        source = self.root / "gen9"
        self.create_bank(source, 3, gen=8)
        item = self.upload(0, root=source)
        self.assertEqual(self.listing(0, 1)[2], [item])
        self.assertEqual(self.box.metadata(item)["offer"]["generations"], 1 << 8)

    def test_3ds_update_is_verified_installed_and_keeps_previous_copy(self):
        install = self.root / "installed.3dsx"
        old = b"existing 3dsx stays recoverable"
        install.write_bytes(old)
        run = subprocess.run(
            [str(UPDATE_PROBE), "127.0.0.1", str(PIN), str(0x300), str(install), "1", str(self.port)],
            text=True, capture_output=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("INSTALLED 0.4.3", run.stdout)
        self.assertEqual(install.read_bytes(), self.update_data)
        self.assertEqual(Path(str(install) + ".previous").read_bytes(), old)

        run = subprocess.run(
            [str(UPDATE_PROBE), "127.0.0.1", str(PIN), str(0x403), str(install), "1", str(self.port)],
            text=True, capture_output=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("CURRENT 0.4.3", run.stdout)
        self.assertEqual(install.read_bytes(), self.update_data)

    def test_3ds_update_cancel_preserves_installed_copy(self):
        install = self.root / "installed.3dsx"
        old = b"do not replace when declined"
        install.write_bytes(old)
        run = subprocess.run(
            [str(UPDATE_PROBE), "127.0.0.1", str(PIN), str(0x300), str(install), "0", str(self.port)],
            text=True, capture_output=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("CANCELLED 0.4.3", run.stdout)
        self.assertEqual(install.read_bytes(), old)

    def test_update_offer_waits_longer_than_general_socket_timeout(self):
        client, server = socket.socketpair()
        server.settimeout(0.02)
        errors = []

        def offer_update():
            try:
                pc.serve_update(server, self.nds_update_path, 0x403, "DS")
            except Exception as error:
                errors.append(error)

        with patch.object(pc, "UPDATE_SOCKET_TIMEOUT_SECONDS", 0.2):
            worker = threading.Thread(target=offer_update)
            worker.start()
            self.assertEqual(pc.result(client), "")
            self.assertEqual(len(pc.exact(client, 48)), 48)
            time.sleep(0.05)
            client.sendall(struct.pack("<I", 0))
            worker.join(1)

        client.close()
        server.close()
        self.assertFalse(worker.is_alive(), "server did not finish the declined update")
        self.assertEqual(errors, [])

    def test_update_stream_tolerates_client_backpressure_longer_than_general_timeout(self):
        client, server = socket.socketpair()
        client.settimeout(2)
        server.settimeout(0.02)
        errors = []

        def send_update():
            try:
                pc.serve_update(server, self.nds_update_path, 0x403, "DS")
            except Exception as error:
                errors.append(error)

        with patch.object(pc, "UPDATE_SOCKET_TIMEOUT_SECONDS", 0.2):
            worker = threading.Thread(target=send_update)
            worker.start()
            self.assertEqual(pc.result(client), "")
            manifest = pc.exact(client, 48)
            self.assertEqual(struct.unpack_from("<I", manifest, 12)[0], len(self.nds_update_data))
            client.sendall(struct.pack("<I", 1))
            self.assertEqual(pc.result(client), "")
            time.sleep(0.05)
            self.assertEqual(pc.exact(client, len(self.nds_update_data)), self.nds_update_data)
            worker.join(2)

        client.close()
        server.close()
        self.assertFalse(worker.is_alive(), "server did not finish streaming the accepted update")
        self.assertEqual(errors, [])

    def test_nds_update_downloads_verified_launchable_copy(self):
        install = self.root / "ChestLink_DS_v0.4.3.nds"
        run = subprocess.run(
            [str(UPDATE_PROBE), "127.0.0.1", str(PIN), str(0x402), str(self.root),
             "1", str(self.port), "ds"],
            text=True, capture_output=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("INSTALLED 0.4.3", run.stdout)
        self.assertEqual(install.read_bytes(), self.nds_update_data)
        self.assertFalse(Path(str(install) + ".previous").exists())
        audit_path = self.box.root / "update-communication.jsonl"
        records = [json.loads(line) for line in audit_path.read_text().splitlines()]
        events = [record["event"] for record in records]
        self.assertIn("authentication_accepted", events)
        self.assertIn("offer_sent", events)
        self.assertIn("decision_received", events)
        self.assertIn("transfer_ack_sent", events)
        self.assertIn("chunk_sent", events)
        self.assertIn("transfer_stream_sent", events)
        self.assertTrue(all(record["console"] == "DS" for record in records))
        self.assertNotIn(str(PIN), audit_path.read_text())

    def test_nds_update_preserves_existing_copy_and_supports_cancel(self):
        install = self.root / "ChestLink_DS_v0.4.3.nds"
        old = b"existing DS app stays recoverable"
        install.write_bytes(old)
        run = subprocess.run(
            [str(UPDATE_PROBE), "127.0.0.1", str(PIN), str(0x402), str(self.root),
             "0", str(self.port), "ds"],
            text=True, capture_output=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("CANCELLED 0.4.3", run.stdout)
        self.assertEqual(install.read_bytes(), old)

        run = subprocess.run(
            [str(UPDATE_PROBE), "127.0.0.1", str(PIN), str(0x402), str(self.root),
             "1", str(self.port), "ds"],
            text=True, capture_output=True, timeout=15)
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertEqual(install.read_bytes(), self.nds_update_data)
        self.assertEqual(Path(str(install) + ".previous").read_bytes(), old)

    def test_3ds_update_hash_mismatch_keeps_installed_and_removes_partial(self):
        install = self.root / "installed.3dsx"
        old = b"keep the last working app"
        install.write_bytes(old)
        original_exact = pc.exact

        def mutate_release(sock, length):
            data = original_exact(sock, length)
            if length == 4:
                self.update_path.write_bytes(bytes([255]) * len(self.update_data))
            return data

        with patch.object(pc, "exact", mutate_release):
            run = subprocess.run(
                [str(UPDATE_PROBE), "127.0.0.1", str(PIN), str(0x300), str(install), "1", str(self.port)],
                text=True, capture_output=True, timeout=15)
        self.assertNotEqual(run.returncode, 0, run.stdout + run.stderr)
        self.assertIn("SHA-256 diferente", run.stderr)
        self.assertEqual(install.read_bytes(), old)
        self.assertFalse(Path(str(install) + ".download").exists())

    def test_pc_restart_preserves_pending_and_saved_pin(self):
        item = self.upload()
        self.stop_server()
        self.box = pc.Mailbox(self.root / "pc")
        self.assertEqual(self.box.pin, PIN)
        self.server = pc.Server(("127.0.0.1", 0), self.box, timeout_seconds=2,
                                update_path=self.update_path, update_version=0x403,
                                nds_update_path=self.nds_update_path,
                                nds_update_version=0x403)
        self.port = self.server.server_address[1]
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.01})
        self.thread.start()
        self.assertEqual(self.listing()[2], [item])
        self.assertIn("IMPORTED", self.fetch(item))

    def test_repeat_upload_and_fetch_reuse_same_copy(self):
        item = self.upload()
        self.assertEqual(self.upload(), item)
        self.fetch(item)
        self.assertIn("REUSED link0001 ACK 1", self.fetch(item))
        self.assertEqual(len(list(self.box.items.iterdir())), 1)
        self.assertEqual(json.loads((self.dst / "banks.json").read_text()), {"link0001": 2})

    def test_all_backups_include_both_roles_and_restore_keeps_intended_queue(self):
        first, second = self.upload(1), self.upload(2)
        self.assertEqual(set(self.listing(0, 1)[2]), {first, second})
        self.assertIn("IMPORTED link0001 ACK 1", self.probe(second, "backup"))
        self.assertEqual(self.listing(2)[2], [second])
        self.assertIn("REUSED link0001 ACK 1", self.fetch(second))
        self.assertEqual(self.listing(2)[2], [])

    def test_lost_pc_final_ack_reports_local_success(self):
        item = self.upload()
        original = pc.reply
        def missing_ack(sock, message="", ok=True):
            if message == "DELIVERED":
                raise ConnectionResetError("Simulated PC lost ACK")
            return original(sock, message, ok)
        with patch.object(pc, "reply", missing_ack):
            self.assertIn("IMPORTED link0001 ACK 0", self.fetch(item))
        self.assertEqual(self.listing()[2], [])
        self.assertIn("REUSED link0001 ACK 1", self.fetch(item))

    def test_failed_delivery_metadata_write_keeps_copy_pending(self):
        item = self.upload()
        with patch.object(pc, "atomic_json", side_effect=OSError("Simulated receipt disk error")):
            self.assertIn("IMPORTED link0001 ACK 0", self.fetch(item))
        self.assertEqual(self.listing()[2], [item])
        self.assertTrue((self.box.items / item / "bank.bnk").exists())
        self.assertIn("REUSED link0001 ACK 1", self.fetch(item))

    def test_shutdown_aborts_partial_upload_and_retains_committed_copy(self):
        item = self.upload()
        sock, _, bank, _ = self.offered_package()
        self.assertEqual(pc.result(sock), "READY")
        sock.sendall(bank[:1000])
        self.stop_server()
        sock.close()
        self.start_server()
        self.wait_incoming_clean()
        self.assertEqual(self.listing()[2], [item])

    def test_missing_final_console_ack_keeps_pending_then_reuses_bank(self):
        item = self.upload()
        self.assertIn("IMPORTED link0001 ACK 0", self.probe(item, "dropack"))
        self.assertEqual(self.listing()[2], [item])
        self.assertIn("REUSED link0001 ACK 1", self.fetch(item))
        self.assertEqual(self.listing()[2], [])

    def test_power_cut_after_registry_commit_recovers_without_duplicate(self):
        item = self.upload()
        self.probe(item, "power9", code=23)
        self.assertTrue((self.dst / "chest-link/journal.json").exists())
        self.assertEqual(self.listing()[2], [item])
        self.assertIn("REUSED link0001 ACK 1", self.fetch(item))
        self.assertFalse((self.dst / "chest-link/journal.json").exists())
        self.assertEqual(json.loads((self.dst / "banks.json").read_text()), {"link0001": 2})

    def test_console_fixed_size_allocator_receives_and_registers(self):
        item = self.upload()
        self.assertIn("IMPORTED link0001 ACK 1", self.probe(item, "fixed"))

    def test_corrupt_in_transit_never_imports_or_marks_delivered(self):
        item = self.upload()
        self.assertIn("SHA-256", self.probe(item, "corrupt", code=1))
        self.assertFalse((self.dst / "banks.json").exists())
        self.assertEqual(self.listing()[2], [item])

    def test_cancel_and_receiver_refusal_keep_pending(self):
        item = self.upload()
        for fault in ("cancel", "refuse"):
            self.probe(item, fault, code=1)
            self.assertFalse((self.dst / "banks.json").exists())
            self.assertEqual(self.listing()[2], [item])
        self.assertIn("IMPORTED", self.fetch(item))

    def test_wrong_pin_never_exposes_list_or_changes_queue(self):
        item = self.upload()
        out = self.cli("mail-list", self.dst, "127.0.0.1", 111111, 2, 0, 0, self.port, ok=False)
        self.assertIn("PIN incorreto", out)
        self.assertNotIn(item, out)
        self.assertEqual(self.listing()[2], [item])

    def test_wrong_target_and_path_like_id_refused(self):
        item = self.upload(2)
        self.assertEqual(self.listing(1)[2], [])
        self.assertIn("outro console", self.fetch(item, 1, ok=False))
        self.assertIn("invalido", self.fetch("../" + "a" * 29, ok=False))
        self.assertFalse((self.dst / "banks.json").exists())

    def test_incomplete_upload_is_not_published(self):
        sock, _, bank, _ = self.offered_package()
        self.assertEqual(pc.result(sock), "READY")
        sock.sendall(bank[:1000])
        sock.close()
        self.wait_incoming_clean()
        self.assertEqual(self.listing()[2], [])
        self.assertEqual(list(self.box.items.iterdir()), [])

    def test_corrupted_upload_and_bad_metadata_are_rejected(self):
        sock, _, bank, names = self.offered_package()
        with sock:
            self.assertEqual(pc.result(sock), "READY")
            corrupt = bytearray(bank)
            corrupt[99] ^= 1
            sock.sendall(corrupt + names)
            with self.assertRaisesRegex(pc.MailboxError, "SHA-256"):
                pc.result(sock)
        sock, _, _, _ = self.offered_package(mutate=lambda o: o.update(bankBytes=0xffffffff))
        with sock, self.assertRaises(pc.MailboxError):
            pc.result(sock)
        sock, _, bank, names = self.offered_package(mutate=lambda o: o.update(occupied=5))
        with sock:
            self.assertEqual(pc.result(sock), "READY")
            sock.sendall(bank + names)
            with self.assertRaisesRegex(pc.MailboxError, "descricao"):
                pc.result(sock)
        self.wait_incoming_clean()
        self.assertEqual(list(self.box.items.iterdir()), [])

    def test_disk_write_failure_never_publishes(self):
        sock, _, bank, names = self.offered_package()
        with patch.object(pc, "json_write_new", side_effect=OSError("Simulated disk full")), sock:
            self.assertEqual(pc.result(sock), "READY")
            sock.sendall(bank + names)
            with self.assertRaisesRegex(pc.MailboxError, "disk full"):
                pc.result(sock)
        self.wait_incoming_clean()
        self.assertEqual(list(self.box.items.iterdir()), [])

    def test_quota_refuses_before_body_and_retains_previous_copies(self):
        item = self.upload()
        self.box.max_bytes = 1
        out = self.cli("mail-send", self.src, "test", "2", "127.0.0.1", PIN, 2, self.port, ok=False)
        self.assertIn("cheia", out)
        self.assertEqual(self.listing()[2], [item])

    def test_unsupported_generation_and_ds_50_box_limit(self):
        other = self.root / "new-source"
        self.create_bank(other, 1, gen=7)
        out = self.cli("mail-send", other, "test", "1", "127.0.0.1", PIN, 1, self.port, ok=False)
        self.assertIn("geracoes", out)
        self.create_bank(other, 51)
        item = self.upload(1, ",".join(str(i + 1) for i in range(51)), other)
        self.assertIn("Limite", self.fetch(item, 1, 50, ok=False))
        self.assertEqual(self.listing(1)[2], [item])
        self.assertFalse((self.dst / "banks.json").exists())

    def test_500_box_streaming_through_pc(self):
        other = self.root / "big-source"
        self.create_bank(other, 500)
        item = self.upload(2, ",".join(str(i + 1) for i in range(500)), other)
        self.assertIn("IMPORTED", self.fetch(item))
        self.assertEqual((self.dst / "banks/link0001.bnk").read_bytes(), (other / "banks/test.bnk").read_bytes())

    def test_list_pagination_and_role_separation(self):
        other = self.root / "many-source"
        self.create_bank(other, 34)
        ids = {self.upload(2, str(i + 1), other) for i in range(34)}
        next_page, total, first = self.listing()
        self.assertEqual((next_page, total, len(first)), (32, 34, 32))
        following, _, second = self.listing(offset=32)
        self.assertEqual(following, 0)
        self.assertEqual(set(first + second), ids)
        self.assertEqual(self.listing(1)[2], [])

    def test_parallel_same_upload_publishes_only_one_package(self):
        outcomes, errors = [], []
        def upload():
            try:
                sock, offer, bank, names = self.offered_package()
                with sock:
                    state = pc.result(sock)
                    if state == "READY":
                        sock.sendall(bank + names)
                        outcomes.append(pc.result(sock))
                    else:
                        outcomes.append(state.split()[1])
            except BaseException as exc:
                errors.append(exc)
        threads = [threading.Thread(target=upload) for _ in range(4)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(errors, [])
        self.assertEqual(len(set(outcomes)), 1)
        self.assertEqual(len(list(self.box.items.iterdir())), 1)
        self.wait_incoming_clean()

    def test_saved_copy_damage_refuses_delivery_and_is_preserved(self):
        item = self.upload()
        path = self.box.items / item / "bank.bnk"
        data = bytearray(path.read_bytes())
        data[99] ^= 1
        path.write_bytes(data)
        self.assertIn("SHA-256", self.fetch(item, ok=False))
        self.assertEqual(path.read_bytes(), data)
        self.assertEqual(self.listing()[2], [item])

    def test_published_upload_survives_sender_missing_ack(self):
        sock, offer, bank, names = self.offered_package()
        self.assertEqual(pc.result(sock), "READY")
        sock.sendall(bank + names)
        sock.close()
        deadline = time.monotonic() + 4
        item = pc.packet_id(2, offer["hash"])
        while not (self.box.items / item).exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.wait_incoming_clean()
        self.assertEqual(self.listing()[2], [item])
        self.assertIn("IMPORTED", self.fetch(item))

    def test_crash_leftovers_cleaned_and_second_server_refused(self):
        with self.assertRaisesRegex(pc.MailboxError, "Ja existe"):
            pc.Mailbox(self.root / "pc", PIN)
        item = self.upload()
        self.stop_server()
        old = self.root / "pc/incoming/stale"
        old.mkdir()
        (old / "partial.bnk").write_bytes(b"incomplete")
        self.start_server()
        self.assertFalse(old.exists())
        self.assertEqual(self.listing()[2], [item])

    def test_malformed_server_list_is_bounded_and_refused(self):
        # Serve an invalid list to the actual C++ parser.
        self.check_malformed_list()

    def test_verification_heartbeats_do_not_mark_delivered(self):
        item = self.upload()
        with self.connection(3) as sock:
            sock.sendall(struct.pack("<I", 2) + item.encode() + struct.pack("<I", 0))
            pc.result(sock)
            offer = pc.offer_decode(pc.exact(sock, 52))
            pc.reply(sock, "READY")
            pc.exact(sock, offer["bankBytes"] + offer["namesBytes"])
            pc.reply(sock, "VERIFY")
            pc.reply(sock, "VERIFY")
            self.assertEqual(self.listing()[2], [item])
            pc.reply(sock, "link0001")
            self.assertEqual(pc.result(sock), "DELIVERED")
        self.assertEqual(self.listing()[2], [])

    def test_damaged_config_and_metadata_refuse_without_rewriting_banks(self):
        other = self.root / "bad-config"
        other.mkdir()
        config = other / "config.json"
        for before in (b'{"unknown":123}', b'null'):
            config.write_bytes(before)
            with self.assertRaisesRegex(pc.MailboxError, "Config"):
                pc.Mailbox(other)
            self.assertEqual(config.read_bytes(), before)
        config.write_text(json.dumps({"pin": PIN}))
        valid = pc.Mailbox(other)
        valid.close()
        item = self.upload()
        folder = self.box.items / item
        bank = (folder / "bank.bnk").read_bytes()
        meta = pc.json_read(folder / "meta.json")
        meta["offer"]["boxes"] = True
        (folder / "meta.json").write_text(json.dumps(meta))
        self.assertIn("invalidos", self.fetch(item, ok=False))
        self.assertEqual((folder / "bank.bnk").read_bytes(), bank)
        self.assertFalse((self.dst / "banks.json").exists())

    def check_malformed_list(self):
        # Serve an invalid list to the actual C++ parser, rather than testing
        # only Python's own JSON library. No destination file may be written.
        for body, length in ((b'{"items":[],"next":1,"total":0}', None), (b'', 65537)):
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            port = listener.getsockname()[1]
            def malicious():
                with listener:
                    peer, _ = listener.accept()
                    with peer:
                        pc.exact(peer, 20)
                        pc.reply(peer)
                        pc.exact(peer, 12)
                        pc.reply(peer)
                        peer.sendall(struct.pack("<I", len(body) if length is None else length) + body)
            thread = threading.Thread(target=malicious)
            thread.start()
            text = self.cli("mail-list", self.dst, "127.0.0.1", PIN, 2, 0, 0, port, ok=False)
            thread.join(timeout=5)
            self.assertIn("PC", text)
        self.assertFalse((self.dst / "banks.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
