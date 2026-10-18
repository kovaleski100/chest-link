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


def make_gen4_hof(revision, team=((157, 50, "CINDY", "ASH", 1234, 4321, 0x10203040),)):
    block = bytearray(saves.GEN4_HOF_SIZE)
    for member_index, (species, level, nickname, ot, tid, sid, pid) in enumerate(team):
        offset = member_index * saves.GEN4_HOF_TEAM_SIZE
        put_u16(block, offset, species)
        block[offset + 2] = level
        put_u32(block, offset + 4, pid)
        put_u16(block, offset + 8, tid)
        put_u16(block, offset + 10, sid)
        block[offset + 12:offset + 34] = encode_text(nickname, 22)
        block[offset + 34:offset + 50] = encode_text(ot, 16)
    footer_start = len(block) - 0x18
    put_u32(block, footer_start, 111)
    put_u32(block, footer_start + 4, revision)
    footer = len(block) - 0x10
    put_u32(block, footer, 0x20060623)
    put_u32(block, footer + 4, revision)
    put_u32(block, footer + 8, len(block) - 0x10)
    put_u16(block, len(block) - 2, saves._crc16_ccitt(block[:-2]))
    return block


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
        if champion:
            hof = make_gen4_hof(2 if active else 1)
            hof_offset = partition + 0x23000
            data[hof_offset:hof_offset + len(hof)] = hof

    if corrupt_active:
        data[saves.PARTITION_SIZE + saves.TRAINER_OFFSET + 0x10] ^= 0x01
    return bytes(data)


def seal_gen4_block(block, major, minor=0):
    footer = len(block) - 0x14
    put_u32(block, footer, major)
    put_u32(block, footer + 4, minor)
    put_u32(block, len(block) - 8, 0x20060623)
    put_u16(block, len(block) - 2, saves._crc16_ccitt(block[:-0x14]))


def build_sinnoh_save(*, version="DP", game_hint="diamond", trainer_id=456,
                      caught=(25, 387), seen=(25, 26, 387), badges=5,
                      game_clear=True, national=True, party_count=1,
                      battle_points=789, corrupt_active=False):
    layout = saves.SinnohSaveParser.LAYOUTS[version]
    data = bytearray(saves.GEN4_DP_SIZE)
    party_mon = make_pk4(0x3456789A, 393, ot="LUCAS")
    box_mon = make_pk4(0x456789AB, 25, form=1, ot="DAWN")
    for partition in (0, saves.PARTITION_SIZE):
        active = partition == saves.PARTITION_SIZE
        general = bytearray(layout["game_size"])
        storage = bytearray(layout["storage_size"])
        trainer = layout["trainer"]
        party = layout["party"]
        dex_offset = layout["dex"]
        general[trainer:trainer + 16] = encode_text("LUCAS" if active else "OLD", 16)
        put_u16(general, trainer + 0x10, trainer_id if active else 999)
        put_u16(general, trainer + 0x12, 654 if active else 888)
        put_u32(general, trainer + 0x14, 123456 if active else 765432)
        general[trainer + 0x18] = 0
        general[trainer + 0x1A] = badges if active else 0
        general[trainer + 0x1D] = (int(game_clear) | (int(national) << 1)) if active else 0
        put_u16(general, trainer + 0x22, 27 if active else 1)
        general[trainer + 0x24] = 13 if active else 0
        general[trainer + 0x25] = 42
        general[party - 4] = party_count if active else 1
        general[party:party + saves.PK4_STORED_SIZE] = party_mon
        put_u16(general, layout["battle_points"], battle_points if active else 0)
        for species in (caught if active else ()):
            bit = species - 1
            general[dex_offset + 4 + (bit >> 3)] |= 1 << (bit & 7)
        for species in (seen if active else ()):
            bit = species - 1
            general[dex_offset + 4 + 0x40 + (bit >> 3)] |= 1 << (bit & 7)
        box_data_size = saves.BOX_SLOTS * saves.PK4_STORED_SIZE
        box_name_start = 4 + saves.BOX_COUNT * box_data_size
        storage[4:4 + saves.PK4_STORED_SIZE] = box_mon
        storage[box_name_start:box_name_start + 40] = encode_text("Sinnoh Box", 40)
        general_crc_corrupt = corrupt_active and active
        if general_crc_corrupt:
            general[trainer + 0x14] ^= 1
        seal_gen4_block(general, 7 if active else 6)
        seal_gen4_block(storage, 7 if active else 6)
        if general_crc_corrupt:
            general[-2] ^= 1
        data[partition:partition + len(general)] = general
        start = layout["game_size"]
        data[partition + start:partition + start + len(storage)] = storage
        if game_clear:
            hof = make_gen4_hof(7 if active else 6)
            hof_offset = partition + 0x20000
            data[hof_offset:hof_offset + len(hof)] = hof
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


class Generation12ParserTests(unittest.TestCase):
    @staticmethod
    def build_gen1(layout_name="international", yellow=False, caught=(1, 151),
                   seen=(1, 7, 151), badges=0xA5, trainer_id=12345):
        layout = saves.GEN1_LAYOUTS[layout_name]
        data = bytearray(saves.GEN1_SIZE)
        for offset in (layout["party"], layout["box"]):
            data[offset:offset + 2] = b"\0\xFF"
        for key, species_ids in (("dex_caught", caught), ("dex_seen", seen)):
            for species_id in species_ids:
                bit = species_id - 1
                data[layout[key] + (bit >> 3)] |= 1 << (bit & 7)
        data[layout["badge"]] = badges
        data[layout["starter"]] = 0x54 if yellow else 0
        struct.pack_into(">H", data, layout["trainer_id"], trainer_id)
        data[layout["play_time"]:layout["play_time"] + 4] = bytes((86, 0, 13, 5))
        data[layout["checksum"]] = (~sum(data[0x2598:layout["checksum"]])) & 0xFF
        return bytes(data)

    @staticmethod
    def build_gen2(layout_name="gs-int", caught=(1, 151, 152, 251),
                   seen=(1, 251), badges=0x5A, kanto_badges=0xA5, trainer_id=45678):
        layout = saves.GEN2_LAYOUTS[layout_name]
        size = saves.GEN2_JPN_SIZE if layout_name.endswith("-jpn") else saves.GEN2_INT_SIZE
        data = bytearray(size)
        for offset in (layout["party"], layout["box"]):
            data[offset:offset + 2] = b"\0\xFF"
        for key, species_ids in (("dex_caught", caught), ("dex_seen", seen)):
            for species_id in species_ids:
                bit = species_id - 1
                data[layout[key] + (bit >> 3)] |= 1 << (bit & 7)
        data[layout["badges"]:layout["badges"] + 2] = bytes((badges, kanto_badges))
        struct.pack_into(">H", data, layout["trainer_id"], trainer_id)
        struct.pack_into(">H", data, layout["play_time"], 321)
        data[layout["play_time"] + 2:layout["play_time"] + 4] = bytes((42, 5))
        checksum = sum(data[0x2009:layout["checksum_end"] + 1]) & 0xFFFF
        for offset in layout["checksum_offsets"]:
            struct.pack_into("<H", data, offset, checksum)
        return bytes(data)

    def parse(self, data):
        source = {"filename": "fixture.sav", "sha256": hashlib.sha256(data).hexdigest()}
        return saves.NativeSaveParser().parse(data, source)

    def test_gen1_detects_red_blue_group_and_reads_saved_flags(self):
        snapshot = self.parse(self.build_gen1())
        self.assertEqual((snapshot["generation"], snapshot["gameVersion"]), (1, "RB"))
        self.assertEqual(snapshot["game"], "Red / Blue")
        self.assertEqual(snapshot["pokedex"]["caught"], [1, 151])
        self.assertEqual(snapshot["pokedex"]["seen"], [1, 7, 151])
        self.assertEqual(snapshot["trainer"]["trainerId"]["value"], 12345)
        self.assertEqual(snapshot["pokedex"]["totalSpecies"], 151)
        self.assertEqual(snapshot["trainer"]["playTime"]["value"]["hours"], 86)
        self.assertEqual(snapshot["supportedFeatures"], ["pokedex", "badges", "trainerId", "playTime"])

    def test_gen1_yellow_and_japanese_layouts_are_distinguished(self):
        yellow = self.parse(self.build_gen1(yellow=True))
        japanese = self.parse(self.build_gen1("japanese"))
        self.assertEqual(yellow["gameVersion"], "YW")
        self.assertEqual(japanese["rawMetadata"]["layout"], "japanese")
        self.assertEqual(japanese["pokedex"]["caught"], [1, 151])

    def test_gen2_detects_all_supported_layouts_and_reads_251_flags(self):
        expected = {"gs-int": "GS", "crystal-int": "C", "gs-jpn": "GS",
                    "crystal-jpn": "C", "gs-kor": "GS"}
        for layout, version in expected.items():
            with self.subTest(layout=layout):
                snapshot = self.parse(self.build_gen2(layout))
                self.assertEqual((snapshot["generation"], snapshot["gameVersion"]), (2, version))
                self.assertEqual(snapshot["rawMetadata"]["layout"], layout)
                self.assertEqual(snapshot["pokedex"]["caught"], [1, 151, 152, 251])
                self.assertEqual(snapshot["pokedex"]["seen"], [1, 251])
                self.assertEqual(snapshot["pokedex"]["totalSpecies"], 251)
                self.assertEqual(snapshot["trainer"]["trainerId"]["value"], 45678)
                self.assertEqual(snapshot["trainer"]["playTime"]["value"]["hours"], 321)
                self.assertEqual(snapshot["trainer"]["playTime"]["value"]["minutes"], 42)
                self.assertEqual(sum(row["acquired"] for row in snapshot["badges"]["johto"]), 4)
                self.assertEqual(sum(row["acquired"] for row in snapshot["badges"]["kanto"]), 4)

    def test_corrupt_generation_two_checksum_is_rejected(self):
        data = bytearray(self.build_gen2("gs-int"))
        data[saves.GEN2_LAYOUTS["gs-int"]["dex_caught"]] ^= 1
        with self.assertRaises(saves.InvalidRawSave):
            self.parse(bytes(data))

    def test_repository_import_detects_generation_two_without_game_metadata(self):
        data = self.build_gen2("crystal-int")
        changed_data = self.build_gen2("crystal-int", caught=(1, 151, 152))
        with tempfile.TemporaryDirectory() as folder:
            repository = saves.SnapshotRepository(folder)
            imported = repository.import_bytes(data, filename="crystal.sav")
            snapshot = repository.snapshot(imported["sha256"])
            second_import = repository.import_bytes(changed_data, filename="crystal-later.sav")
            second_snapshot = repository.snapshot(second_import["sha256"])
        self.assertEqual((imported["state"], imported["gameVersion"]), ("supported", "C"))
        self.assertEqual(snapshot["pokedex"]["caught"], [1, 151, 152, 251])
        self.assertIsNone(second_snapshot["comparison"])


class Generation3ParserTests(unittest.TestCase):
    @staticmethod
    def encode_text(text, length):
        result = bytearray([0xFF] * length)
        for index, char in enumerate(text[:length]):
            if "A" <= char <= "Z": result[index] = 0xBB + ord(char) - ord("A")
            elif "a" <= char <= "z": result[index] = 0xD5 + ord(char) - ord("a")
            elif "0" <= char <= "9": result[index] = 0xA1 + ord(char) - ord("0")
            else: raise ValueError(f"unsupported Gen III fixture character {char!r}")
        return result

    @classmethod
    def make_pk3(cls, species, trainer_id=0x10E104D2, pid=0x12345678):
        record = bytearray(saves.PK3_STORED_SIZE)
        put_u32(record, 0, pid); put_u32(record, 4, trainer_id); record[0x13] = 0x02
        record[0x14:0x1B] = cls.encode_text("KOVAL", 7)
        canonical = bytearray(0x30)
        put_u16(canonical, 0, pokemon.CATALOG["g3ToSpecies"].index(species))
        put_u16(record, 0x1C, sum(struct.unpack("<24H", canonical)) & 0xFFFF)
        order = pokemon.CATALOG["blockPositions"][(pid % 24) * 4:(pid % 24) * 4 + 4]
        stored = bytearray(0x30)
        for canonical_index, stored_index in enumerate(order):
            stored[stored_index * 12:(stored_index + 1) * 12] = \
                canonical[canonical_index * 12:(canonical_index + 1) * 12]
        record[0x20:0x50] = stored
        key = pid ^ trainer_id
        for offset in range(0x20, 0x50):
            record[offset] ^= (key >> ((offset & 3) * 8)) & 0xFF
        return bytes(record)

    @classmethod
    def build_save(cls, variant="RS", *, caught=(1, 252, 386), seen=(1, 2, 252, 386),
                   national=False, badges=(0, 3, 7), clear=False, name="KOVAL"):
        layout = saves.GEN3_LAYOUTS[variant]
        lengths = saves.GEN3_SECTION_LENGTHS[variant]
        block1, block2 = bytearray(layout["block1Size"]), bytearray(layout["block2Size"])
        storage = bytearray(saves.GEN3_STORAGE_SIZE)
        block2[:7] = cls.encode_text(name, 7); block2[8] = 1
        put_u32(block2, 0x0A, 0x10E104D2); struct.pack_into("<H", block2, 0x0E, 87)
        block2[0x10:0x12] = bytes((12, 34))
        block2[saves.FRLG_POKEDEX_OFFSET + 2] = 0xDA if national else 0
        for ids, start in ((caught, saves.FRLG_DEX_OWNED_OFFSET), (seen, saves.FRLG_DEX_SEEN_OFFSET)):
            for species in ids:
                bit = species - 1; block2[start + (bit >> 3)] |= 1 << (bit & 7)

        def set_flag(flag_id, enabled=True):
            if enabled:
                offset = layout["flagsOffset"] + flag_id // 8
                block1[offset] |= 1 << (flag_id & 7)
        set_flag(layout["systemFlags"] + saves.GEN3_POKEDEX_RECEIVED_FLAG)
        set_flag(layout["systemFlags"] + saves.GEN3_GAME_CLEAR_FLAG, clear)
        set_flag(layout["systemFlags"] + saves.GEN3_NATIONAL_DEX_FLAG, national)
        for index in badges: set_flag(layout["systemFlags"] + saves.GEN3_BADGE_FLAG_START + index)
        set_flag(0xE4)
        if variant == "E":
            set_flag(layout["systemFlags"] + 0x48)
            put_u32(block2, layout["encryptionKey"], 0x11223344)
        block1[layout["partyCount"]] = 1
        mon = cls.make_pk3(252)
        block1[layout["party"]:layout["party"] + len(mon)] = mon
        money = 12345
        if layout["encryptionKey"] is not None:
            money ^= struct.unpack_from("<I", block2, layout["encryptionKey"])[0]
        put_u32(block1, layout["money"], money)
        block1[layout["rematches"] + 3] = 1
        storage[0] = 0
        mon = cls.make_pk3(386)
        start = saves.FRLG_BOXES_OFFSETS[0]
        storage[start:start + len(mon)] = mon
        for box in range(saves.FRLG_BOX_COUNT):
            start = saves.FRLG_BOX_NAMES_OFFSET + box * 9
            storage[start:start + 8] = cls.encode_text(f"BOX{box + 1}", 8)

        sections = {0: bytes(block2)}
        cursor = 0
        for section_id in range(1, 5):
            length = lengths[section_id]
            sections[section_id] = bytes(block1[cursor:cursor + length]); cursor += length
        cursor = 0
        for section_id in range(5, 14):
            length = lengths[section_id]
            sections[section_id] = bytes(storage[cursor:cursor + length]); cursor += length
        data = bytearray(saves.FRLG_SIZE)
        for section_id, payload in sections.items():
            sector = bytearray(saves.FRLG_SECTOR_SIZE); sector[:len(payload)] = payload
            struct.pack_into("<HHII", sector, 0xFF4, section_id,
                             saves._frlg_checksum(payload), saves.FRLG_SAVE_MAGIC, 7)
            offset = section_id * saves.FRLG_SECTOR_SIZE
            data[offset:offset + len(sector)] = sector
        return bytes(data)

    @classmethod
    def build_frlg_save(cls, caught=(1, 151), seen=(1, 151)):
        lengths = saves.FRLG_SECTION_LENGTHS
        block1, block2 = bytearray(saves.FRLG_SAVE_BLOCK1_SIZE), bytearray(lengths[0])
        storage = bytearray(sum(lengths[5:]))
        block2[:7] = cls.encode_text("KOVAL", 7)
        put_u32(block2, saves.FRLG_TRAINER_ID_OFFSET, 0x10E104D2)
        struct.pack_into("<H", block2, saves.FRLG_PLAY_TIME_OFFSET, 10)
        for ids, start in ((caught, saves.FRLG_DEX_OWNED_OFFSET),
                           (seen, saves.FRLG_DEX_SEEN_OFFSET)):
            for species in ids:
                bit = species - 1; block2[start + (bit >> 3)] |= 1 << (bit & 7)
        for flag_id in (saves.FRLG_BADGE_FLAG_START, saves.FRLG_BADGE_FLAG_START + 4,
                        saves.FRLG_POKEDEX_FLAG, saves.FRLG_GAME_CLEAR_FLAG):
            offset = saves.FRLG_SAVE_BLOCK1_FLAGS_OFFSET + flag_id // 8
            block1[offset] |= 1 << (flag_id & 7)
        sections = {0: bytes(block2)}
        cursor = 0
        for section_id in range(1, 5):
            length = lengths[section_id]
            sections[section_id] = bytes(block1[cursor:cursor + length]); cursor += length
        cursor = 0
        for section_id in range(5, 14):
            length = lengths[section_id]
            sections[section_id] = bytes(storage[cursor:cursor + length]); cursor += length
        data = bytearray(saves.FRLG_SIZE)
        for section_id, payload in sections.items():
            sector = bytearray(saves.FRLG_SECTOR_SIZE); sector[:len(payload)] = payload
            struct.pack_into("<HHII", sector, 0xFF4, section_id,
                             saves._frlg_checksum(payload), saves.FRLG_SAVE_MAGIC, 7)
            offset = section_id * saves.FRLG_SECTOR_SIZE
            data[offset:offset + len(sector)] = sector
        return bytes(data)

    @staticmethod
    def parse(data, filename, game_hint=None):
        source = {"filename": filename, "sha256": hashlib.sha256(data).hexdigest()}
        if game_hint is not None:
            source["gameHint"] = game_hint
        return saves.NativeSaveParser().parse(data, source)

    def test_ruby_sapphire_and_emerald_read_their_game_specific_layouts(self):
        for variant, filename, game in (("RS", "Ruby.sav", "Ruby"),
                                         ("RS", "Sapphire.sav", "Sapphire"),
                                         ("E", "Emerald.sav", "Emerald")):
            with self.subTest(variant=variant, filename=filename):
                snapshot = self.parse(self.build_save(variant), filename)
                self.assertEqual((snapshot["generation"], snapshot["game"], snapshot["gameVersion"]),
                                 (3, game, "RS" if variant == "RS" else "E"))
                self.assertEqual(snapshot["trainer"]["name"]["value"], "KOVAL")
                self.assertEqual(snapshot["trainer"]["trainerId"]["value"], 1234)
                self.assertEqual(snapshot["trainer"]["secretId"]["value"], 4321)
                self.assertEqual(snapshot["trainer"]["money"]["value"], 12345)
                self.assertEqual(snapshot["trainer"]["playTime"]["value"]["hours"], 87)
                self.assertEqual(snapshot["pokedex"]["caught"], [1, 252, 386])
                self.assertEqual(snapshot["pokedex"]["seen"], [1, 2, 252, 386])
                self.assertEqual(snapshot["pokedex"]["regionalSpecies"], 202)
                self.assertEqual(snapshot["pokedex"]["regionName"], "Hoenn")
                self.assertEqual(snapshot["party"][0]["species"], 252)
                self.assertEqual(snapshot["boxes"][0]["pokemon"][0]["species"], 386)
                self.assertTrue(snapshot["badges"]["hoenn"][0]["acquired"])
                self.assertFalse(snapshot["badges"]["hoenn"][1]["acquired"])
                self.assertTrue(snapshot["story"]["regi_doors_opened"]["value"])
                self.assertEqual(snapshot["miscellany"]["trainerRematches"]["activeCount"], 1)
                self.assertEqual(snapshot["hallOfFame"]["count"], 0)
                report = saves.CompletionTracker.evaluate(snapshot)
                story_group = next(group for group in report["groups"] if group["id"] == "story")
                if variant == "E":
                    self.assertTrue(snapshot["story"]["frontier_unlocked"]["value"])
                    self.assertIn("minigames", snapshot["completionData"])
                    self.assertEqual(report["profile"]["id"], "emerald-observable-v1")
                    self.assertIn("minigames", {group["id"] for group in report["groups"]})
                    self.assertEqual(story_group["total"], 3)
                else:
                    self.assertEqual(snapshot["story"]["frontier_unlocked"]["state"], "unsupported")
                    self.assertNotIn("minigames", snapshot["completionData"])
                    self.assertEqual(report["profile"]["id"], "gen3-observable-v1")
                    self.assertNotIn("minigames", {group["id"] for group in report["groups"]})
                    self.assertEqual(story_group["total"], 2)

    def test_native_generation_three_catalog_has_both_regions_and_five_games(self):
        catalog = json.loads((ROOT / "server/web/assets/dex-gen3.json").read_text())
        self.assertEqual(len(catalog["species"]), 386)
        self.assertEqual([game["id"] for game in catalog["games"]],
                         ["firered", "leafgreen", "ruby", "sapphire", "emerald"])
        regions = {row["id"]: row for row in catalog["regions"]}
        self.assertEqual(len(regions["hoenn"]["speciesIds"]), 202)
        self.assertEqual(len(regions["kanto"]["speciesIds"]), 151)
        self.assertIn("leafgreen", regions["kanto"]["games"])
        self.assertNotIn("ruby", regions["kanto"]["games"])
        species = {row["id"]: row for row in catalog["species"]}
        self.assertEqual(species[183]["types"], ["Water"])
        self.assertEqual(species[282]["types"], ["Psychic"])
        self.assertEqual(species[303]["types"], ["Steel"])
        self.assertFalse(any("Fairy" in row["types"] for row in catalog["species"]))

    def test_firered_and_leafgreen_remain_distinct_native_snapshots(self):
        data = self.build_frlg_save()
        for filename, version, game in (("FireRed.sav", "FR", "FireRed"),
                                         ("LeafGreen.sav", "LG", "LeafGreen")):
            with self.subTest(filename=filename):
                snapshot = self.parse(data, filename)
                self.assertEqual((snapshot["game"], snapshot["gameVersion"]), (game, version))
                self.assertEqual(snapshot["pokedex"]["caught"], [1, 151])
                self.assertEqual(snapshot["pokedex"]["regionalSpecies"], 151)
                self.assertEqual(set(snapshot["badges"]), {"kanto"})
                self.assertNotIn("hoenn", snapshot["badges"])

    def test_ruby_and_sapphire_snapshots_cannot_be_compared_as_the_same_game(self):
        ruby = self.parse(self.build_save("RS"), "Ruby.sav")
        sapphire = self.parse(self.build_save("RS", caught=(1, 252)), "Sapphire.sav")
        with self.assertRaises(saves.NativeSaveError):
            saves.SnapshotComparator.compare(ruby, sapphire)

    def test_selected_game_disambiguates_shared_generation_three_sector_layouts(self):
        ruby_save = self.build_save("RS")
        frlg_save = self.build_frlg_save()
        self.assertEqual(saves.GameDetector().detect(ruby_save, "save.sav")["state"], "unknown")
        self.assertEqual(self.parse(ruby_save, "save.sav", "sapphire")["game"], "Sapphire")
        self.assertEqual(self.parse(frlg_save, "save.sav", "leafgreen")["gameVersion"], "LG")
        with tempfile.TemporaryDirectory() as folder:
            repository = saves.SnapshotRepository(folder)
            imported = repository.import_bytes(ruby_save, filename="save.sav", game_hint="sapphire")
            snapshot = repository.snapshot(imported["sha256"])
        self.assertEqual((imported["state"], imported["game"]), ("supported", "Sapphire"))
        self.assertEqual(snapshot["pokedex"]["regionName"], "Hoenn")


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
        self.assertEqual(snapshot["hallOfFame"]["count"], 1)
        self.assertEqual(snapshot["hallOfFame"]["entries"][0]["pokemon"][0]["species"], 157)
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


class SinnohParserTests(unittest.TestCase):
    def parse(self, data, *, filename="sinnoh.sav", game_hint="diamond"):
        source = dict(kind="test", filename=filename, gameHint=game_hint,
                      sha256=hashlib.sha256(data).hexdigest())
        return saves.NativeSaveParser().parse(data, source)

    def test_detects_and_parses_diamond_pearl_and_platinum_layouts(self):
        for hint, expected in (("diamond", "Diamond"), ("pearl", "Pearl")):
            with self.subTest(game=hint):
                data = build_sinnoh_save(game_hint=hint)
                detected = saves.GameDetector().detect(data, "save.sav", hint)
                snapshot = self.parse(data, game_hint=hint)
                self.assertEqual((detected["generation"], detected["gameVersion"]), (4, "DP"))
                self.assertEqual(snapshot["game"], expected)
                self.assertEqual(snapshot["pokedex"]["regionalSpecies"], 151)

        data = build_sinnoh_save(version="PT", game_hint="platinum")
        snapshot = self.parse(data, filename="Platinum.sav", game_hint="platinum")
        self.assertEqual((snapshot["game"], snapshot["gameVersion"]), ("Platinum", "PT"))
        self.assertEqual(snapshot["pokedex"]["regionalSpecies"], 210)

    def test_reads_sinnoh_trainer_party_box_dex_badges_story_and_points(self):
        data = build_sinnoh_save()
        snapshot = self.parse(data, game_hint="pearl")
        self.assertEqual(snapshot["generation"], 4)
        self.assertEqual(snapshot["game"], "Pearl")
        self.assertEqual(snapshot["trainer"]["name"]["value"], "LUCAS")
        self.assertEqual(snapshot["trainer"]["trainerId"]["value"], 456)
        self.assertEqual(snapshot["trainer"]["money"]["value"], 123456)
        self.assertEqual(snapshot["trainer"]["playTime"]["value"]["totalSeconds"], 27 * 3600 + 13 * 60 + 42)
        self.assertEqual(snapshot["party"][0]["species"], 393)
        self.assertEqual(snapshot["party"][0]["offset"], saves.PARTITION_SIZE + saves.GEN4_DP_PARTY_OFFSET)
        self.assertEqual(snapshot["boxes"][0]["name"], "Sinnoh Box")
        box_data_size = saves.BOX_SLOTS * saves.PK4_STORED_SIZE
        expected_box_offset = saves.PARTITION_SIZE + saves.GEN4_DP_GENERAL_SIZE + 4
        self.assertEqual(snapshot["boxes"][0]["pokemon"][0]["offset"], expected_box_offset)
        self.assertEqual(snapshot["pokedex"]["caught"], [25, 387])
        self.assertEqual(snapshot["pokedex"]["seen"], [25, 26, 387])
        self.assertEqual(snapshot["badges"]["sinnoh"][0], {"name": "Coal", "acquired": True})
        self.assertTrue(snapshot["story"]["game_clear"]["value"])
        self.assertTrue(snapshot["story"]["national_dex"]["value"])
        self.assertEqual(snapshot["miscellany"]["battlePoints"]["value"], 789)
        self.assertEqual(snapshot["hallOfFame"]["count"], 1)
        hof_member = snapshot["hallOfFame"]["entries"][0]["pokemon"][0]
        self.assertEqual((hof_member["species"], hof_member["name"], hof_member["nickname"],
                          hof_member["level"]), (157, "Bayleef", "CINDY", 50))
        self.assertEqual(snapshot["rawMetadata"]["activeBlocks"]["general"]["active_partition"], 1)
        report = saves.CompletionTracker.evaluate(snapshot)
        self.assertEqual(report["profile"]["id"], "sinnoh-observable-v1")
        self.assertFalse(report["game100PercentConfirmed"])

    def test_uses_selected_title_for_shared_diamond_pearl_binary_and_filename_fallback(self):
        data = build_sinnoh_save()
        source = dict(kind="test", filename="save.sav", sha256=hashlib.sha256(data).hexdigest())
        self.assertEqual(saves.NativeSaveParser().parse(data, source)["game"], "Diamond / Pearl")
        source["filename"] = "Pokemon Pearl Version.sav"
        self.assertEqual(saves.NativeSaveParser().parse(data, source)["game"], "Pearl")

    def test_rejects_corrupt_active_sinnoh_checksum_and_party_count(self):
        with self.assertRaises(saves.InvalidRawSave):
            self.parse(build_sinnoh_save(corrupt_active=True))
        with self.assertRaises(saves.InvalidRawSave):
            self.parse(build_sinnoh_save(party_count=7))


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
