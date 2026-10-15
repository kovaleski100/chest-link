"""Synthetic HGSS fixtures for the read-only Native Saves pipeline.

These fixtures exercise documented binary layout and checksum paths. They are
not substitutes for comparisons against real cartridge dumps.
"""
import hashlib
import http.client
import json
from pathlib import Path
import struct
import sys
import tempfile
import threading
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from server import chest_link_server as pc
from server import native_saves as saves, pokemon
from server.interface import Interface


def put_u16(data, offset, value):
    struct.pack_into("<H", data, offset, value)


def put_u32(data, offset, value):
    struct.pack_into("<I", data, offset, value)


def encode_text(text, byte_length):
    punctuation = {
        "!": 0x1AB, "?": 0x1AC, ",": 0x1AD, ".": 0x1AE,
        "'": 0x1B3, "(": 0x1B9, ")": 0x1BA, "+": 0x1BD,
        "-": 0x1BE, "*": 0x1BF, "#": 0x1C0, "=": 0x1C1,
        "&": 0x1C2, "~": 0x1C3, ":": 0x1C4, ";": 0x1C5,
        "@": 0x1D0, "%": 0x1D2, " ": 0x1DE,
    }
    codes = []
    for char in text:
        if "0" <= char <= "9":
            codes.append(0x121 + ord(char) - ord("0"))
        elif "A" <= char <= "Z":
            codes.append(0x12B + ord(char) - ord("A"))
        elif "a" <= char <= "z":
            codes.append(0x145 + ord(char) - ord("a"))
        elif char in punctuation:
            codes.append(punctuation[char])
        else:
            raise ValueError(f"unsupported fixture character {char!r}")
    codes = codes[:byte_length // 2]
    codes.extend([0xFFFF] * (byte_length // 2 - len(codes)))
    return struct.pack("<" + "H" * len(codes), *codes)


def make_pk4(pid, species, trainer_id=1234, secret_id=4321, form=0,
             ot="ASH", met_date=(12, 4, 7), met_location=42):
    decrypted = bytearray(saves.PK4_STORED_SIZE)
    put_u32(decrypted, 0, pid)
    put_u16(decrypted, 8, species)
    put_u16(decrypted, 12, trainer_id)
    put_u16(decrypted, 14, secret_id)
    decrypted[0x40] = form << 3
    put_u16(decrypted, 0x46, met_location)
    decrypted[0x68:0x76] = encode_text(ot, 14)
    decrypted[0x7B:0x7E] = bytes(met_date)
    checksum = sum(struct.unpack_from("<64H", decrypted, 8)) & 0xFFFF
    put_u16(decrypted, 6, checksum)

    order_start = ((pid >> 13) & 31) % 24 * 4
    order = pokemon.CATALOG["blockPositions"][order_start:order_start + 4]
    canonical = bytes(decrypted[8:])
    shuffled = bytearray(len(canonical))
    for canonical_index, encrypted_index in enumerate(order):
        shuffled[encrypted_index * 32:(encrypted_index + 1) * 32] = canonical[
            canonical_index * 32:(canonical_index + 1) * 32]
    seed = checksum
    for offset in range(0, len(shuffled), 2):
        seed = (seed * 0x41C64E6D + 0x6073) & 0xFFFFFFFF
        value = struct.unpack_from("<H", shuffled, offset)[0] ^ (seed >> 16)
        put_u16(shuffled, offset, value)
    return bytes(decrypted[:8] + shuffled)


def seal_block(block, major, minor=0):
    footer = len(block) - 0x14
    put_u32(block, footer, major)
    put_u32(block, footer + 4, minor)
    put_u32(block, len(block) - 8, 0x20060623)
    put_u16(block, len(block) - 2, saves._crc16_ccitt(block[:-0x10]))


def build_save(*, version=0x47, trainer_id=321, caught=(25,), seen=(25, 26),
               johto_badges=3, kanto_badges=1, champion=True, national=True,
               kanto_unlocked=True, battle_points=456, hours=42, minutes=15,
               unown=(0, 3), party_count=1, corrupt_active=False, invalid_unown=False):
    data = bytearray(saves.HGSS_SIZE)
    party_mon = make_pk4(0x12345678, 157)
    box_mon = make_pk4(0x23456789, 25, form=1, ot="RED", met_location=88)

    for partition in (0, saves.PARTITION_SIZE):
        active = partition == saves.PARTITION_SIZE
        general = bytearray(saves.GENERAL_SIZE)
        storage = bytearray(saves.STORAGE_SIZE)
        general[0x64:0x74] = encode_text("ASH" if active else "OLD", 16)
        put_u16(general, 0x64 + 0x10, trainer_id if active else 999)
        put_u16(general, 0x64 + 0x12, 777 if active else 888)
        put_u32(general, 0x64 + 0x14, 123456 if active else 765432)
        general[0x64 + 0x18] = 0
        general[0x64 + 0x1A] = johto_badges if active else 0
        general[0x64 + 0x1C] = version
        general[0x64 + 0x1D] = (int(champion) | (int(national) << 1)) if active else 0
        general[0x64 + 0x1F] = kanto_badges if active else 0
        put_u16(general, 0x64 + 0x22, hours if active else 1)
        general[0x64 + 0x24] = minutes if active else 0
        general[0x64 + 0x25] = 30
        general[0x94] = party_count if active else 1
        general[0x98:0x98 + saves.PK4_STORED_SIZE] = party_mon
        map_state = 2 if kanto_unlocked else 0
        general[0xBAE7] = (map_state << 3) if active else 0
        put_u16(general, 0x5BB8, battle_points if active else 10)
        for species in (caught if active else ()):
            bit = species - 1
            general[saves.DEX_OFFSET + 4 + (bit >> 3)] |= 1 << (bit & 7)
        for species in (seen if active else ()):
            bit = species - 1
            general[saves.DEX_OFFSET + 4 + 0x40 + (bit >> 3)] |= 1 << (bit & 7)
        dex_forms = bytearray([0xFF] * 0x1C)
        forms = list(unown)
        if invalid_unown:
            forms = [0, 0]
        dex_forms[:len(forms)] = bytes(forms)
        unown_start = saves.DEX_OFFSET + 0x10C
        general[unown_start:unown_start + 0x1C] = dex_forms

        storage[0: saves.PK4_STORED_SIZE] = box_mon
        storage[0x12008:0x12008 + 40] = encode_text("Box One" if active else "Old Box", 40)
        for box in range(1, saves.BOX_COUNT):
            storage[0x12008 + box * 40:0x12008 + (box + 1) * 40] = encode_text(
                f"Box{box + 1}", 40)
        seal_block(general, 2 if active else 1)
        seal_block(storage, 2 if active else 1)
        general_offset = partition
        storage_offset = partition + saves.STORAGE_START
        data[general_offset:general_offset + len(general)] = general
        data[storage_offset:storage_offset + len(storage)] = storage

    if corrupt_active:
        data[saves.PARTITION_SIZE + saves.TRAINER_OFFSET + 0x10] ^= 0x01
    return bytes(data)


class RawSaveSourceTests(unittest.TestCase):
    def test_reads_hashes_and_preserves_input(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.sav"
            original = b"save bytes\x00\xff"
            path.write_bytes(original)
            data, metadata = saves.RawFileSaveSource(path).read()
            self.assertEqual(data, original)
            self.assertEqual(metadata["sha256"], hashlib.sha256(original).hexdigest())
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(metadata["kind"], "raw_file")

    def test_rejects_empty_oversized_and_non_file_sources(self):
        with tempfile.TemporaryDirectory() as folder:
            empty = Path(folder) / "empty.sav"
            empty.write_bytes(b"")
            with self.assertRaises(saves.InvalidRawSave):
                saves.RawFileSaveSource(empty).read()
            full = Path(folder) / "full.sav"
            full.write_bytes(b"123")
            with self.assertRaises(saves.InvalidRawSave):
                saves.RawFileSaveSource(full, max_bytes=2).read()
            with self.assertRaises(saves.InvalidRawSave):
                saves.RawFileSaveSource(folder).read()


class HGSSParserTests(unittest.TestCase):
    def setUp(self):
        self.parser = saves.HGSSSaveParser()

    def parse(self, data):
        return self.parser.parse(data, dict(kind="test", sha256=hashlib.sha256(data).hexdigest()))

    def test_detects_supported_versions_and_rejects_unknown_or_truncated(self):
        self.assertEqual(saves.GameDetector().detect(build_save(version=0x47))["game"], "HeartGold")
        self.assertEqual(saves.GameDetector().detect(build_save(version=0x53))["game"], "SoulSilver")
        with self.assertRaises(saves.UnsupportedRawSave):
            self.parse(b"not a supported save")
        with self.assertRaises(saves.InvalidRawSave):
            self.parse(build_save()[:-1])

    def test_parses_trainer_party_boxes_dex_progress_and_active_copies(self):
        snapshot = self.parse(build_save())
        self.assertEqual(snapshot["game"], "HeartGold")
        self.assertEqual(snapshot["trainer"]["name"]["value"], "ASH")
        self.assertEqual(snapshot["trainer"]["trainerId"]["value"], 321)
        self.assertEqual(snapshot["trainer"]["secretId"]["value"], 777)
        self.assertEqual(snapshot["trainer"]["money"]["value"], 123456)
        self.assertEqual(snapshot["trainer"]["playTime"]["value"]["totalSeconds"], 42 * 3600 + 15 * 60 + 30)
        self.assertEqual(snapshot["party"][0]["species"], 157)
        self.assertEqual(snapshot["party"][0]["offset"], saves.PARTITION_SIZE + saves.PARTY_OFFSET)
        self.assertEqual(snapshot["boxes"][0]["name"], "Box One")
        self.assertEqual(snapshot["boxes"][0]["pokemon"][0]["species"], 25)
        self.assertEqual(snapshot["boxes"][0]["pokemon"][0]["offset"],
                         saves.PARTITION_SIZE + saves.STORAGE_START)
        self.assertEqual(snapshot["pokedex"]["caught"], [25])
        self.assertEqual(snapshot["pokedex"]["seen"], [25, 26])
        self.assertEqual(snapshot["badges"]["johto"][0]["acquired"], True)
        self.assertEqual(snapshot["story"]["kanto_unlocked"]["value"], True)
        self.assertEqual(snapshot["story"]["battle_frontier"]["value"]["bp"], 456)
        self.assertEqual(snapshot["collections"]["unownForms"], [0, 3])
        self.assertEqual(snapshot["rawMetadata"]["activeBlocks"]["general"]["active_partition"], 1)
        self.assertEqual(snapshot["rawMetadata"]["activeBlocks"]["storage"]["active_partition"], 1)

    def test_rejects_bad_active_checksum_and_invalid_party_count(self):
        with self.assertRaises(saves.InvalidRawSave):
            self.parse(build_save(corrupt_active=True))
        with self.assertRaises(saves.InvalidRawSave):
            self.parse(build_save(party_count=7))

    def test_unown_forms_with_invalid_structure_are_unknown(self):
        snapshot = self.parse(build_save(invalid_unown=True))
        self.assertEqual(snapshot["collections"]["unownStatus"], "unknown")
        self.assertIsNone(snapshot["collections"]["unownCount"])

    def test_gen4_text_ascii_subset_uses_documented_punctuation_codes(self):
        encoded = encode_text("A!?,.()", 16)
        self.assertEqual(saves._decode_gen4_text(encoded), "A!?,.()")


class SnapshotRepositoryTests(unittest.TestCase):
    def test_imports_immutable_snapshots_compares_progress_and_builds_journey(self):
        before = build_save(caught=(25,), seen=(25, 26), johto_badges=1,
                            battle_points=40, hours=10, minutes=10, unown=(0,))
        after = build_save(caught=(25, 26), seen=(25, 26, 27), johto_badges=7,
                           battle_points=55, hours=11, minutes=5, unown=(0, 3))
        with tempfile.TemporaryDirectory() as folder:
            repo = saves.SnapshotRepository(folder)
            first = repo.import_bytes(before, "../../first.sav")
            source_copy = repo.saves_dir / f"{first['sha256']}.sav"
            self.assertEqual(source_copy.read_bytes(), before)
            self.assertEqual(first["filename"], "first.sav")
            duplicate = repo.import_bytes(before, "renamed.sav")
            self.assertEqual(duplicate["sha256"], first["sha256"])
            self.assertEqual(len(repo.list_saves()), 1)

            second = repo.import_bytes(after, "second.sav")
            comparison = repo.compare(first["sha256"], second["sha256"])
            self.assertEqual(comparison["badgeAdditions"], ["johto:Hive", "johto:Plain"])
            self.assertEqual(comparison["caughtDelta"], 1)
            self.assertEqual(comparison["battlePointsDelta"], 15)
            self.assertEqual(comparison["unownDelta"], 1)
            self.assertEqual(comparison["playTimeDeltaSeconds"], 3300)
            self.assertEqual(comparison["newPokemon"], 0)

            collection = repo.collection()
            observed_party = next(mon for mon in collection if mon["species"] == 157)
            self.assertEqual(observed_party["identityStatus"], "INFERRED")
            self.assertEqual(len(observed_party["observations"]), 2)
            self.assertTrue(all(row["identityStatus"] != "CONFIRMED"
                                for row in observed_party["observations"]))

            journey = repo.journey(second["sha256"])
            self.assertTrue(any(event["source"] == "DIRECT" for event in journey["events"]))
            self.assertTrue(any(event["source"] == "INFERRED" and "Badge" in event["label"]
                                for event in journey["events"]))
            manual = repo.add_manual_event({"saveHash": second["sha256"], "label": "Cheguei a Kanto"})
            self.assertEqual(manual["source"], "MANUAL")
            self.assertTrue(any(event["source"] == "MANUAL"
                                for event in repo.journey(second["sha256"])["events"]))
            report = repo.completion(second["sha256"])
            self.assertEqual(report["profile"]["id"], "hgss-observable-v1")
            self.assertFalse(report["game100PercentConfirmed"])
            self.assertFalse(report["completeWithinProfile"])

    def test_unknown_saves_are_preserved_but_invalid_candidates_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            repo = saves.SnapshotRepository(folder)
            unknown = b"a readable save from an unsupported game"
            result = repo.import_bytes(unknown, "other.sav")
            self.assertEqual(result["state"], "unsupported")
            self.assertEqual((repo.saves_dir / f"{result['sha256']}.sav").read_bytes(), unknown)
            with self.assertRaises(saves.InvalidRawSave):
                repo.import_bytes(build_save()[:-1], "truncated.sav")
            self.assertEqual(len(repo.list_saves()), 1)


class NativeSaveHttpTests(unittest.TestCase):
    def test_native_parser_is_packaged_and_watched_for_server_updates(self):
        package = (ROOT / "tools/package.py").read_text(encoding="utf-8")
        server = (ROOT / "server/chest_link_server.py").read_text(encoding="utf-8")
        self.assertIn('"PC/servidor.py": ROOT / "server/pc_launcher.py"', package)
        self.assertNotIn('"PC/native_saves.py":', package)
        self.assertIn('script.with_name("native_saves.py")', server)

    def test_supported_upload_and_native_saves_api(self):
        with tempfile.TemporaryDirectory(prefix="chest-native-http-") as folder:
            root = Path(folder)
            mailbox = pc.Mailbox(root / "pc", 123456)
            tcp = pc.Server(("127.0.0.1", 0), mailbox, timeout_seconds=2)
            worker = threading.Thread(target=tcp.serve_forever,
                                      kwargs={"poll_interval": 0.01})
            worker.start()
            interface = Interface(pc, mailbox, tcp.server_address,
                                  ["192.168.1.101"], 0)
            interface.start(False)
            try:
                data = build_save()
                connection = http.client.HTTPConnection(
                    "127.0.0.1", interface.server.server_port, timeout=15)
                connection.request("POST", "/api/native-saves/import", body=data,
                                   headers={
                                       "Authorization": "Bearer " + interface.token,
                                       "Content-Type": "application/octet-stream",
                                       "Origin": f"http://127.0.0.1:{interface.server.server_port}",
                                       "X-Filename": "direct.sav",
                })
                response = connection.getresponse()
                response_body = response.read()
                self.assertEqual(response.status, 200, response_body)
                imported = json.loads(response_body)
                connection.close()
                self.assertEqual(imported["state"], "supported")
                self.assertEqual(imported["game"], "HeartGold")
                self.assertEqual((interface.native_saves.saves_dir /
                                  f"{imported['sha256']}.sav").read_bytes(), data)

                def get(path):
                    request = http.client.HTTPConnection(
                        "127.0.0.1", interface.server.server_port, timeout=15)
                    request.request("GET", path, headers={
                        "Authorization": "Bearer " + interface.token,
                    })
                    result = request.getresponse()
                    body = result.read()
                    request.close()
                    self.assertEqual(result.status, 200, body)
                    return json.loads(body)

                digest = imported["sha256"]
                snapshot = get("/api/native-saves/snapshot?id=" + digest)
                self.assertEqual(snapshot["trainer"]["trainerId"]["value"], 321)
                collection = get("/api/native-saves/collection")
                self.assertEqual(len(collection), 2)
                journey = get("/api/native-saves/journey?id=" + digest)
                self.assertTrue(any(event["source"] == "DIRECT"
                                    for event in journey["events"]))
                completion = get("/api/native-saves/completion?id=" + digest)
                self.assertEqual(completion["profile"]["id"], "hgss-observable-v1")
            finally:
                interface.close()
                tcp.shutdown()
                tcp.server_close()
                worker.join(timeout=5)
                mailbox.close()


if __name__ == "__main__":
    unittest.main()
