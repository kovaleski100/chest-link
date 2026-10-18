"""Read-only raw-save acquisition and normalized game parsers.

FireRed/LeafGreen layout follows pret/pokefirered's public save structures;
Gen I/II and HGSS layouts follow public PKHeX and pret format references. No
upstream implementation code is copied here; format facts are documented in
docs/NATIVE_SAVES.md.
"""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import stat
import struct
import tempfile
import threading
import uuid

try:
    from . import pokemon
except ImportError:
    import pokemon


MAX_RAW_SAVE_BYTES = 64 * 1024 * 1024
HGSS_SIZE = 0x80000
GEN4_DP_SIZE = 0x80000
GEN4_DP_GENERAL_SIZE = 0xC100
GEN4_DP_STORAGE_SIZE = 0x121E0
GEN4_PT_GENERAL_SIZE = 0xCF2C
GEN4_PT_STORAGE_SIZE = 0x121E4
GEN4_DP_DEX_OFFSET = 0x12DC
GEN4_DP_TRAINER_OFFSET = 0x64
GEN4_DP_PARTY_OFFSET = 0x98
GEN4_PT_DEX_OFFSET = 0x1328
GEN4_PT_TRAINER_OFFSET = 0x68
GEN4_PT_PARTY_OFFSET = 0xA0
FRLG_SIZE = 0x20000
GEN1_SIZE = 0x8000
GEN2_INT_SIZE = 0x8000
GEN2_JPN_SIZE = 0x10000
PARTITION_SIZE = 0x40000
GENERAL_SIZE = 0xF628
STORAGE_START = 0xF700
STORAGE_SIZE = 0x12310
GENERAL_START = 0
DEX_OFFSET = 0x12B8
TRAINER_OFFSET = 0x64
PARTY_OFFSET = 0x98
PARTY_COUNT_OFFSET = PARTY_OFFSET - 4
PK4_STORED_SIZE = 0x88
PK4_PARTY_SIZE = 0xEC
BOX_COUNT = 18
BOX_SLOTS = 30
BOX_SIZE = 0x1000
DEX_SPECIES_COUNT = 493
GEN4_HOF_SIZE = 0x2AC0
GEN4_HOF_ENTRY_SIZE = 0x16C
GEN4_HOF_TEAM_SIZE = 0x3C
GEN4_HOF_ENTRY_COUNT = 30
SAVE_MAGIC = {0x20060623, 0x20070903}
ROM_VERSIONS = {0x47: "HeartGold", 0x53: "SoulSilver"}
SINNOH_BADGE_NAMES = ("Coal", "Forest", "Cobble", "Fen", "Relic", "Mine", "Icicle", "Beacon")
GEN1_LAYOUTS = {
    "international": dict(party=0x2F2C, box=0x30C0, max_count=20,
                           dex_caught=0x25A3, dex_seen=0x25B6,
                           starter=0x29C3, pikachu_friendship=0x271C,
                           checksum=0x3523, badge=0x2602, trainer_id=0x2605,
                           play_time=0x2CED),
    "japanese": dict(party=0x2ED5, box=0x302D, max_count=30,
                      dex_caught=0x259E, dex_seen=0x25B1,
                      starter=0x29B9, pikachu_friendship=0x2712,
                      checksum=0x3594, badge=0x25F8, trainer_id=0x25FB,
                      play_time=0x2CA0),
}
GEN2_LAYOUTS = {
    "gs-int": dict(game="Gold / Silver", game_version="GS", generation=2,
                   party=0x288A, box=0x2D6C, max_count=20,
                   dex_caught=0x2A4C, dex_seen=0x2A6C,
                   checksum_end=0x2D68, checksum_offsets=(0x2D69, 0x7E6D),
                   trainer_id=0x2009, badges=0x23E4, play_time=0x2053),
    "crystal-int": dict(game="Crystal", game_version="C", generation=2,
                        party=0x2865, box=0x2D10, max_count=20,
                        dex_caught=0x2A27, dex_seen=0x2A47,
                        checksum_end=0x2B82, checksum_offsets=(0x2D0D, 0x1F0D),
                        trainer_id=0x2009, badges=0x23E5, play_time=0x2052),
    "gs-jpn": dict(game="Gold / Silver", game_version="GS", generation=2,
                   party=0x283E, box=0x2D10, max_count=30,
                   dex_caught=0x29CE, dex_seen=0x29EE,
                   checksum_end=0x2C8B, checksum_offsets=(0x2D0D, 0x7F0D),
                   trainer_id=0x2009, badges=0x23C5, play_time=0x2034),
    "crystal-jpn": dict(game="Crystal", game_version="C", generation=2,
                        party=0x281A, box=0x2D10, max_count=30,
                        dex_caught=0x29AA, dex_seen=0x29CA,
                        checksum_end=0x2AE2, checksum_offsets=(0x2D0D, 0x7F0D),
                        trainer_id=0x2009, badges=0x23C7, play_time=0x2034),
    "gs-kor": dict(game="Gold / Silver", game_version="GS", generation=2,
                   party=0x28CC, box=0x2DAE, max_count=20,
                   dex_caught=0x2A8E, dex_seen=0x2AAE,
                   checksum_end=0x2DAA, checksum_offsets=(0x2DAB, 0x7E6B),
                   trainer_id=0x2009, badges=0x23DC, play_time=0x204D),
}
FRLG_SECTION_LENGTHS = (0xF24, 0xF80, 0xF80, 0xF80, 0xEE8,
                        *([0xF80] * 8), 0x7D0)
FRLG_SECTOR_SIZE = 0x1000
FRLG_SECTOR_DATA_SIZE = 0xF80
FRLG_SECTOR_COUNT = 14
FRLG_SLOT_COUNT = 2
FRLG_BOX_COUNT = 14
FRLG_BOX_SLOTS = 30
PK3_STORED_SIZE = 0x50
PK3_PARTY_SIZE = 0x64
FRLG_BADGE_FLAG_START = 0x820
FRLG_POKEDEX_FLAG = 0x829
FRLG_GAME_CLEAR_FLAG = 0x82C
FRLG_NATIONAL_DEX_FLAG = 0x840
FRLG_SEVII_123_FLAG = 0x845
FRLG_SEVII_4567_FLAG = 0x846
FRLG_TANOBY_RUINS_FLAG = 0x849
FRLG_LOSTELLE_RESCUED_FLAG = 0x2A3
FRLG_SEVII_DETOUR_FINISHED_FLAG = 0x2A1
FRLG_ROCKET_WAREHOUSE_CLEARED_FLAG = 0x2D5
FRLG_SAPPHIRE_RECOVERED_FLAG = 0x2DC
FRLG_RUBY_RECOVERED_FLAG = 0x2DD
FRLG_BADGE_NAMES = ("Boulder", "Cascade", "Thunder", "Rainbow",
                    "Soul", "Marsh", "Volcano", "Earth")
FRLG_DEX_SPECIES_COUNT = 386
FRLG_KANTO_DEX_SPECIES_COUNT = 151
FRLG_NATIONAL_DEX_EXCLUDED = frozenset((151, 249, 250, 251, 385, 386))
FRLG_FAME_CHECKER_OFFSET = 0x3A54
FRLG_FAME_CHECKER_PEOPLE = (
    "Professor Oak", "Daisy", "Brock", "Misty", "Lt. Surge", "Erika", "Koga",
    "Sabrina", "Blaine", "Lorelei", "Bruno", "Agatha", "Lance", "Bill",
    "Mr. Fuji", "Giovanni",
)
FRLG_TRAINER_TOWER_OFFSET = 0x3D38
FRLG_TRAINER_TOWER_MODES = ("Single", "Double", "Knockout", "Mixed")
FRLG_POKEMON_JUMP_OFFSET = 0x0B00
FRLG_DODRIO_BERRY_PICK_OFFSET = 0x0B10
FRLG_SAVE_MAGIC = 0x08012025
FRLG_HOF_SECTOR_IDS = (28, 29)
FRLG_NATURE_NAMES = (
    "Hardy", "Lonely", "Brave", "Adamant", "Naughty",
    "Bold", "Docile", "Relaxed", "Impish", "Lax",
    "Timid", "Hasty", "Serious", "Jolly", "Naive",
    "Modest", "Mild", "Quiet", "Bashful", "Rash",
    "Calm", "Gentle", "Sassy", "Careful", "Quirky",
)
FRLG_HOF_TEAM_COUNT = 50
FRLG_HOF_TEAM_SIZE = 6 * 20
FRLG_HOF_MON_SIZE = 20
FRLG_TRAINER_FLAG_START = 0x500
FRLG_TRAINER_FIRST_ID = 89
FRLG_TRAINER_LAST_ID = 742
FRLG_HIDDEN_ITEM_UNUSED_FLAGS = frozenset((1007, 1016, 1040, 1043,
                                           1044, 1045, 1046, 1124))
FRLG_HIDDEN_ITEM_FLAG_IDS = tuple(
    flag_id for flag_id in range(1000, 1191)
    if flag_id not in FRLG_HIDDEN_ITEM_UNUSED_FLAGS)
FRLG_HIDDEN_ITEM_RECORDS = json.loads(
    Path(__file__).with_name("frlg_hidden_items.json").read_text(encoding="utf-8"))
FRLG_TRAINER_RECORDS = json.loads(
    Path(__file__).with_name("frlg_trainers.json").read_text(encoding="utf-8"))
if (len(FRLG_HIDDEN_ITEM_RECORDS) != len(FRLG_HIDDEN_ITEM_FLAG_IDS) or
        {record.get("flagId") for record in FRLG_HIDDEN_ITEM_RECORDS} !=
        set(FRLG_HIDDEN_ITEM_FLAG_IDS)):
    raise RuntimeError("A lista de itens ocultos FireRed não corresponde às flags do jogo.")
if ([record.get("trainerId") for record in FRLG_TRAINER_RECORDS] !=
        list(range(FRLG_TRAINER_FIRST_ID, FRLG_TRAINER_LAST_ID + 1))):
    raise RuntimeError("A lista de treinadores FireRed não corresponde aos IDs do jogo.")
FRLG_SAVE_BLOCK1_SIZE = 0x3D68
FRLG_STORAGE_SIZE = 0x83C3
FRLG_BOXES_OFFSETS = (0x0001, 0x0004)
FRLG_BOX_NAMES_OFFSET = 0x8344
FRLG_SAVE_BLOCK1_FLAGS_OFFSET = 0x0EE0
FRLG_SAVE_BLOCK1_VARS_OFFSET = 0x1000
FRLG_MONEY_OFFSET = 0x0290
FRLG_ENCRYPTION_KEY_OFFSET = 0x0F20
FRLG_PLAYER_NAME_OFFSET = 0x0000
FRLG_TRAINER_GENDER_OFFSET = 0x0008
FRLG_TRAINER_ID_OFFSET = 0x000A
FRLG_PLAY_TIME_OFFSET = 0x000E
FRLG_POKEDEX_OFFSET = 0x0018
FRLG_DEX_OWNED_OFFSET = FRLG_POKEDEX_OFFSET + 0x10
FRLG_DEX_SEEN_OFFSET = FRLG_POKEDEX_OFFSET + 0x44
GEN3_SECTOR_DATA_SIZE = 0xF80
GEN3_STORAGE_SIZE = 0x83D0
GEN3_SAVE_BLOCK1_RS_SIZE = 0x3AC0
GEN3_SAVE_BLOCK1_E_SIZE = 0x3D88
GEN3_SAVE_BLOCK2_RS_SIZE = 0x890
GEN3_SAVE_BLOCK2_E_SIZE = 0xF2C
GEN3_SECTION_LENGTHS = {
    # SaveBlock1/2 and PokemonStorage chunks from the public pokeruby and
    # pokeemerald save layouts. FRLG retains its already-supported section map.
    "RS": (GEN3_SAVE_BLOCK2_RS_SIZE, *([GEN3_SECTOR_DATA_SIZE] * 3), 0xC40,
           *([GEN3_SECTOR_DATA_SIZE] * 8), 0x7D0),
    "E": (GEN3_SAVE_BLOCK2_E_SIZE, *([GEN3_SECTOR_DATA_SIZE] * 3), 0xF08,
          *([GEN3_SECTOR_DATA_SIZE] * 8), 0x7D0),
    "FRLG": FRLG_SECTION_LENGTHS,
}
GEN3_LAYOUTS = {
    "RS": dict(game="Ruby / Sapphire", region="Hoenn", systemFlags=0x800,
               flagsOffset=0x1220, block1Size=GEN3_SAVE_BLOCK1_RS_SIZE,
               block2Size=GEN3_SAVE_BLOCK2_RS_SIZE, partyCount=0x234,
               party=0x238, money=0x490, encryptionKey=None,
               rematches=0x97A, rematchCount=100, regionalSpecies=202),
    "E": dict(game="Emerald", region="Hoenn", systemFlags=0x860,
              flagsOffset=0x1270, block1Size=GEN3_SAVE_BLOCK1_E_SIZE,
              block2Size=GEN3_SAVE_BLOCK2_E_SIZE, partyCount=0x234,
              party=0x238, money=0x490, encryptionKey=0xAC,
              rematches=0x9CA, rematchCount=100, regionalSpecies=202),
}
GEN3_BADGE_NAMES = ("Stone", "Knuckle", "Dynamo", "Heat", "Balance", "Feather", "Mind", "Rain")
GEN3_GAME_CLEAR_FLAG = 0x04
GEN3_POKEDEX_RECEIVED_FLAG = 0x01
GEN3_NATIONAL_DEX_FLAG = 0x36
GEN3_BADGE_FLAG_START = 0x07
BADGE_NAMES = {
    "johto": ("Zephyr", "Hive", "Plain", "Fog", "Storm", "Mineral", "Glacier", "Rising"),
    "kanto": ("Boulder", "Cascade", "Thunder", "Rainbow", "Soul", "Marsh", "Volcano", "Earth"),
    "sinnoh": SINNOH_BADGE_NAMES,
}
_NAMESPACE = uuid.UUID("bcf3bd11-8547-42c5-a2be-b52bce03888f")


def _trainer_key(snapshot):
    trainer = snapshot.get("trainer", {})
    return tuple(trainer.get(key, {}).get("value")
                 for key in ("trainerId", "secretId", "name"))


def _trainer_identity_reliable(snapshot):
    trainer = snapshot.get("trainer", {})
    trainer_id = trainer.get("trainerId", {})
    name = trainer.get("name", {})
    return (trainer_id.get("state") == "supported" and trainer_id.get("value") is not None and
            name.get("state") == "supported" and isinstance(name.get("value"), str) and
            bool(name["value"].strip()))


class NativeSaveError(Exception):
    """Base error for native save acquisition and parsing."""


class InvalidRawSave(NativeSaveError):
    """The file is incomplete, unreadable, or internally inconsistent."""


class UnsupportedRawSave(NativeSaveError):
    """The raw file is readable, but its game format is not supported yet."""


class SnapshotRepositoryError(NativeSaveError):
    """Persistent Native Saves metadata is invalid or could not be saved."""


def _g12_list_valid(data, offset, maximum):
    return (0 <= offset < len(data) and
            (count := data[offset]) <= maximum and
            offset + 1 + count < len(data) and data[offset + 1 + count] == 0xFF)


def _gen2_checksum_valid(data, layout):
    end = layout["checksum_end"]
    if end >= len(data) or any(offset + 2 > len(data) for offset in layout["checksum_offsets"]):
        return False
    expected = sum(data[0x2009:end + 1]) & 0xFFFF
    return all(struct.unpack_from("<H", data, offset)[0] == expected
               for offset in layout["checksum_offsets"])


def _detect_gen12(data):
    if len(data) == GEN1_SIZE:
        matches = [(key, layout) for key, layout in GEN1_LAYOUTS.items()
                   if _g12_list_valid(data, layout["party"], layout["max_count"])
                   and _g12_list_valid(data, layout["box"], layout["max_count"])]
        if len(matches) == 1:
            key, layout = matches[0]
            yellow = (data[layout["starter"]] == 0x54 or
                      data[layout["starter"]] == 0 and data[layout["pikachu_friendship"]] != 0)
            version = "YW" if yellow else "RB"
            return dict(game="Yellow" if yellow else "Red / Blue",
                        gameVersion=version, generation=1,
                        region="Kanto", layout=key, state="candidate")

    if len(data) in (GEN2_INT_SIZE, GEN2_JPN_SIZE):
        japanese = len(data) == GEN2_JPN_SIZE
        candidates = [(key, layout) for key, layout in GEN2_LAYOUTS.items()
                      if (key.endswith("-jpn") == japanese and
                          _g12_list_valid(data, layout["party"], layout["max_count"]) and
                          _g12_list_valid(data, layout["box"], layout["max_count"]))]
        valid_checksums = [(key, layout) for key, layout in candidates
                           if _gen2_checksum_valid(data, layout)]
        if len(valid_checksums) == 1:
            candidates = valid_checksums
        if len(candidates) == 1:
            key, layout = candidates[0]
            return dict(game=layout["game"], gameVersion=layout["game_version"],
                        generation=2, region="Johto", layout=key, state="candidate")
    return None


def _gen3_slot(data, slot, variant):
    """Validate one rotating 14-sector Generation III save slot."""
    sections, sector_offsets, counters = {}, {}, set()
    lengths = GEN3_SECTION_LENGTHS[variant]
    for sector_index in range(FRLG_SECTOR_COUNT):
        offset = (slot * FRLG_SECTOR_COUNT + sector_index) * FRLG_SECTOR_SIZE
        block = data[offset:offset + FRLG_SECTOR_SIZE]
        if len(block) != FRLG_SECTOR_SIZE:
            return None
        section_id, checksum, magic, counter = struct.unpack_from("<HHII", block, 0xFF4)
        if (section_id >= FRLG_SECTOR_COUNT or section_id in sections or
                magic != FRLG_SAVE_MAGIC):
            return None
        if _frlg_checksum(block[:lengths[section_id]]) != checksum:
            return None
        sections[section_id] = block[:lengths[section_id]]
        sector_offsets[section_id] = offset
        counters.add(counter)
    if len(sections) != FRLG_SECTOR_COUNT or len(counters) != 1:
        return None
    return dict(slot=slot, counter=counters.pop(), sections=sections,
                sectorOffsets=sector_offsets)


def _gen3_filename_variant(filename):
    normalized = "".join(char for char in str(filename).casefold() if char.isalnum())
    if "leafgreen" in normalized or "firered" in normalized:
        return "FRLG"
    if "emerald" in normalized:
        return "E"
    if "ruby" in normalized or "sapphire" in normalized:
        return "RS"
    return None


def _gen3_game_hint_variant(game_hint):
    return {
        "firered": "FRLG", "leafgreen": "FRLG", "ruby": "RS", "sapphire": "RS",
        "emerald": "E",
    }.get(str(game_hint or "").casefold())


def _gen3_game_name(variant, filename="", game_hint=None):
    normalized = "".join(char for char in str(filename).casefold() if char.isalnum())
    if variant == "FRLG":
        if str(game_hint or "").casefold() == "firered":
            return "FireRed"
        if str(game_hint or "").casefold() == "leafgreen":
            return "LeafGreen"
        return _frlg_game_name(filename)
    if variant == "RS":
        if str(game_hint or "").casefold() == "sapphire":
            return "Sapphire"
        if str(game_hint or "").casefold() == "ruby":
            return "Ruby"
        if "sapphire" in normalized:
            return "Sapphire"
        if "ruby" in normalized:
            return "Ruby"
        return "Ruby / Sapphire"
    return "Emerald"


def _detect_gen3(data, filename="", game_hint=None):
    if len(data) != FRLG_SIZE:
        return None
    matches = []
    for variant in ("RS", "E", "FRLG"):
        slots = [parsed for index in range(FRLG_SLOT_COUNT)
                 if (parsed := _gen3_slot(data, index, variant)) is not None]
        if slots:
            matches.append((variant, slots))
    selected_hint = _gen3_game_hint_variant(game_hint)
    file_hint = _gen3_filename_variant(filename)
    if len(matches) == 1:
        variant, slots = matches[0]
        game = _gen3_game_name(variant, filename, game_hint)
        game_version = ("FR" if game == "FireRed" else "LG" if game == "LeafGreen" else
                        "FRLG" if variant == "FRLG" else
                        "RS" if game in ("Ruby", "Sapphire", "Ruby / Sapphire") else "E")
        return dict(game=game, gameVersion=game_version, generation=3,
                    variant=variant, slots=slots,
                    region="Kanto" if variant == "FRLG" else "Hoenn", state="candidate")
    elif len(matches) > 1:
        by_variant = {variant: slots for variant, slots in matches}
        variant_hint = selected_hint if selected_hint in by_variant else file_hint
        if variant_hint not in by_variant:
            return None
        variant, slots = variant_hint, by_variant[variant_hint]
        game = _gen3_game_name(variant, filename, game_hint)
        game_version = ("FR" if game == "FireRed" else "LG" if game == "LeafGreen" else
                        "FRLG" if variant == "FRLG" else
                        "RS" if variant == "RS" else "E")
        return dict(game=game, gameVersion=game_version, generation=3,
                    variant=variant, slots=slots,
                    region="Kanto" if variant == "FRLG" else "Hoenn", state="candidate")
    hinted = selected_hint or file_hint
    if hinted:
        game = _gen3_game_name(hinted, filename, game_hint)
        game_version = ("FR" if game == "FireRed" else "LG" if game == "LeafGreen" else
                        "FRLG" if hinted == "FRLG" else
                        "RS" if hinted == "RS" else "E")
        return dict(game=game, gameVersion=game_version, generation=3,
                    variant=hinted, region="Kanto" if hinted == "FRLG" else "Hoenn",
                    state="candidate")
    return None


def _gen4_layout_has_magic(data, start, length):
    if len(data) != GEN4_DP_SIZE:
        return False
    return any(_u32(data, partition + start + length - 8) in SAVE_MAGIC
               for partition in (0, PARTITION_SIZE)
               if partition + start + length <= len(data))


def _gen4_named_game(game_hint=None, filename=""):
    hint = str(game_hint or "").casefold().replace(" ", "")
    normalized = "".join(char for char in str(filename).casefold() if char.isalnum())
    for game in ("diamond", "pearl", "platinum", "heartgold", "soulsilver"):
        if hint == game or game in normalized:
            return game
    return None


def _detect_gen4(data, filename="", game_hint=None):
    """Identify Gen IV saves by their independent, checksummed main blocks."""
    if len(data) != GEN4_DP_SIZE:
        return None
    named_game = _gen4_named_game(game_hint, filename)
    layouts = (
        ("PT", "Platinum", GEN4_PT_GENERAL_SIZE, GEN4_PT_STORAGE_SIZE),
        ("DP", "Diamond / Pearl", GEN4_DP_GENERAL_SIZE, GEN4_DP_STORAGE_SIZE),
        ("HGSS", None, GENERAL_SIZE, STORAGE_SIZE),
    )
    for code, default_name, general_size, storage_size in layouts:
        storage_start = (STORAGE_START if code == "HGSS" else general_size)
        if not (_gen4_layout_has_magic(data, 0, general_size) and
                _gen4_layout_has_magic(data, storage_start, storage_size)):
            continue
        if code == "HGSS":
            versions = {data[partition + TRAINER_OFFSET + 0x1C]
                        for partition in (0, PARTITION_SIZE)}
            versions.intersection_update(ROM_VERSIONS)
            if not versions:
                continue
            version = next(iter(versions))
            return dict(game=ROM_VERSIONS[version], gameVersion="HG" if version == 0x47 else "SS",
                        generation=4, region="Johto", state="candidate")
        if code == "PT":
            return dict(game="Platinum", gameVersion="PT", generation=4,
                        region="Sinnoh", state="candidate")
        game = named_game if named_game in ("diamond", "pearl") else None
        if game is None:
            return dict(game="Diamond / Pearl", gameVersion="DP", generation=4,
                        region="Sinnoh", state="candidate")
        return dict(game=game.title(), gameVersion="DP", generation=4,
                    region="Sinnoh", state="candidate")
    return None


class GameDetector:
    """Recognize supported save layouts from their structure, not extension."""

    def detect(self, data, filename="", game_hint=None):
        data = bytes(data)
        gen12 = _detect_gen12(data)
        if gen12:
            return gen12
        gen3 = _detect_gen3(data, filename, game_hint)
        if gen3:
            return gen3
        gen4 = _detect_gen4(data, filename, game_hint)
        if gen4:
            return gen4
        candidates = ({data[offset + TRAINER_OFFSET + 0x1C]
                       for offset in (0, PARTITION_SIZE)
                       if len(data) > offset + TRAINER_OFFSET + 0x1C}
                      if len(data) >= HGSS_SIZE - (FRLG_SECTOR_SIZE * 4) else set())
        matches = candidates & ROM_VERSIONS.keys()
        if len(matches) == 1:
            version = next(iter(matches))
            return dict(game=ROM_VERSIONS[version], gameVersion="HG" if version == 0x47 else "SS",
                        state="candidate")
        return dict(game=None, state="unknown")


class GameSaveParser:
    """Base protocol for parsers that produce normalized read-only snapshots."""

    def parse(self, data, source):
        raise NotImplementedError


class Generation12SaveParser(GameSaveParser):
    """Read the saved seen/caught flags from raw Gen I and II battery saves."""

    def parse(self, data, source):
        data = bytes(data)
        detected = _detect_gen12(data)
        if not detected:
            raise UnsupportedRawSave("Formato bruto de Pokémon Red, Blue, Yellow, Gold, Silver ou Crystal não reconhecido.")
        layout_name = detected["layout"]
        if detected["generation"] == 1:
            layout = GEN1_LAYOUTS[layout_name]
            checksum = (~sum(data[0x2598:layout["checksum"]])) & 0xFF
            if data[layout["checksum"]] != checksum:
                raise InvalidRawSave("Checksum da cópia da Geração I inválido.")
            game_version = detected["gameVersion"]
            dex_offset_caught, dex_offset_seen = layout["dex_caught"], layout["dex_seen"]
            species_count = 151
            badge_names = BADGE_NAMES["kanto"]
            badge_data = data[layout["badge"]]
            trainer_id = struct.unpack_from(">H", data, layout["trainer_id"])[0]
            play_time_offset = layout["play_time"]
            hours, minutes, seconds = (data[play_time_offset], data[play_time_offset + 2],
                                       data[play_time_offset + 3])
            play_time_maxed = data[play_time_offset + 1] != 0
            region_name = "Kanto"
            generation = 1
        else:
            layout = GEN2_LAYOUTS[layout_name]
            if not _gen2_checksum_valid(data, layout):
                raise InvalidRawSave("Checksums da cópia da Geração II inválidos.")
            game_version = detected["gameVersion"]
            dex_offset_caught, dex_offset_seen = layout["dex_caught"], layout["dex_seen"]
            species_count = 251
            badge_names = BADGE_NAMES["johto"]
            badge_data = struct.unpack_from("<H", data, layout["badges"])[0]
            trainer_id = struct.unpack_from(">H", data, layout["trainer_id"])[0]
            play_time_offset = layout["play_time"]
            hours = struct.unpack_from(">H", data, play_time_offset)[0]
            minutes, seconds = data[play_time_offset + 2], data[play_time_offset + 3]
            play_time_maxed = False
            region_name = "Johto"
            generation = 2

        def read_flags(offset):
            return [species for species in range(1, species_count + 1)
                    if data[offset + ((species - 1) >> 3)] & (1 << ((species - 1) & 7))]

        caught, seen = read_flags(dex_offset_caught), read_flags(dex_offset_seen)
        unsupported = _field(None, "unsupported", "Geração I/II: campo fora do escopo do parser atual")
        if generation == 1:
            badges = {"kanto": [dict(name=name, acquired=bool(badge_data & (1 << index)))
                                 for index, name in enumerate(badge_names)]}
        else:
            badges = {
                "johto": [dict(name=name, acquired=bool(badge_data & (1 << index)))
                          for index, name in enumerate(BADGE_NAMES["johto"])],
                "kanto": [dict(name=name, acquired=bool(badge_data & (1 << (index + 8))))
                          for index, name in enumerate(BADGE_NAMES["kanto"])],
            }
        play_time_valid = minutes < 60 and seconds < 60
        play_time = (dict(hours=hours, minutes=minutes, seconds=seconds,
                          totalSeconds=(None if play_time_maxed else
                                        hours * 3600 + minutes * 60 + seconds))
                     if play_time_valid else None)
        source_record = dict(kind=source.get("kind", "raw_file"),
                             locator=source.get("locator"), sizeBytes=len(data),
                             sha256=source["sha256"])
        return dict(
            schemaVersion=1,
            generation=generation,
            game=detected["game"],
            gameVersion=game_version,
            saveHash=source["sha256"],
            observedAt=datetime.now(timezone.utc).isoformat(),
            trainer={
                "name": _field(None, "unsupported", "Codificação de texto Gen I/II ainda não decodificada"),
                "trainerId": _field(trainer_id),
                "secretId": unsupported,
                "gender": unsupported,
                "money": unsupported,
                "playTime": _field(play_time, "supported" if play_time_valid else "unknown"),
            },
            party=[], boxes=[], pokemon=[],
            pokedex=dict(seen=seen, caught=caught, seenCount=len(seen),
                         caughtCount=len(caught), nationalDex=False,
                         totalSpecies=species_count, regionalSpecies=species_count,
                         regionName=region_name),
            badges=badges,
            collections=dict(unownForms=[], unownCount=None, unownStatus="unsupported"),
            story={"national_dex": unsupported, "game_clear": unsupported,
                   "johto_champion": unsupported, "kanto_unlocked": unsupported},
            supportedFeatures=["pokedex", "badges", "trainerId", "playTime"],
            rawMetadata=dict(source=source_record, parser="Generation12SaveParser",
                             checksum="valid", layout=layout_name),
        )


class NativeSaveParser(GameSaveParser):
    """Route an input to a parser after checking its binary layout."""

    def __init__(self):
        self.gen12 = Generation12SaveParser()
        self.frlg = FireRedSaveParser()
        self.rse = RubySapphireEmeraldSaveParser()
        self.sinnoh = SinnohSaveParser()
        self.hgss = HGSSSaveParser()

    def parse(self, data, source):
        detected = GameDetector().detect(data, source.get("filename", ""), source.get("gameHint"))
        if detected.get("generation") in (1, 2):
            return self.gen12.parse(data, source)
        if detected.get("variant") in GEN3_LAYOUTS:
            return self.rse.parse(data, source)
        if detected["state"] == "candidate" and detected["gameVersion"] in ("FR", "LG", "FRLG"):
            return self.frlg.parse(data, source)
        if detected.get("gameVersion") in ("DP", "PT"):
            return self.sinnoh.parse(data, source)
        if detected["state"] == "candidate":
            return self.hgss.parse(data, source)
        raise UnsupportedRawSave("Jogo não reconhecido como save nativo das Gerações I a IV compatíveis.")


class RawFileSaveSource:
    """Read one stable file snapshot without opening it for writing."""

    def __init__(self, path, max_bytes=MAX_RAW_SAVE_BYTES):
        self.path = Path(path)
        self.max_bytes = int(max_bytes)
        if not str(self.path) or self.max_bytes <= 0:
            raise ValueError("Caminho e limite do arquivo devem ser validos.")

    def read(self):
        try:
            with self.path.open("rb") as stream:
                before = os.fstat(stream.fileno())
                if not stat.S_ISREG(before.st_mode):
                    raise InvalidRawSave("A origem nao e um arquivo regular.")
                if before.st_size <= 0:
                    raise InvalidRawSave("O arquivo de save esta vazio.")
                if before.st_size > self.max_bytes:
                    raise InvalidRawSave("O arquivo excede o limite de leitura configurado.")
                digest = hashlib.sha256()
                chunks = []
                total = 0
                while True:
                    chunk = stream.read(min(1024 * 1024, self.max_bytes + 1 - total))
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > self.max_bytes:
                        raise InvalidRawSave("O arquivo excede o limite de leitura configurado.")
                    chunks.append(chunk)
                    digest.update(chunk)
                after = os.fstat(stream.fileno())
                if (total != before.st_size or before.st_dev != after.st_dev or
                        before.st_ino != after.st_ino or before.st_size != after.st_size or
                        before.st_mtime_ns != after.st_mtime_ns):
                    raise InvalidRawSave("O arquivo mudou durante a leitura.")
        except InvalidRawSave:
            raise
        except OSError as exc:
            raise InvalidRawSave("Nao foi possivel ler o arquivo de save.") from exc
        data = b"".join(chunks)
        return data, dict(kind="raw_file", locator=self.path.name, sizeBytes=total,
                          sha256=digest.hexdigest())


def _u16(data, offset):
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


def _filename_says_frlg(filename):
    normalized = "".join(char for char in str(filename).casefold() if char.isalnum())
    return "firered" in normalized or "leafgreen" in normalized


def _frlg_game_name(filename, game_hint=None):
    if str(game_hint or "").casefold() == "firered":
        return "FireRed"
    if str(game_hint or "").casefold() == "leafgreen":
        return "LeafGreen"
    normalized = "".join(char for char in str(filename).casefold() if char.isalnum())
    if "leafgreen" in normalized:
        return "LeafGreen"
    if "firered" in normalized:
        return "FireRed"
    return "FireRed / LeafGreen"


def _frlg_checksum(data):
    if len(data) % 4:
        return None
    total = sum(struct.unpack("<" + "I" * (len(data) // 4), data)) & 0xFFFFFFFF
    return ((total >> 16) + (total & 0xFFFF)) & 0xFFFF


def _frlg_slot(data, slot):
    """Return one complete, checksummed FRLG slot and raw sector offsets."""
    sections, sector_offsets, counters = {}, {}, set()
    for sector_index in range(FRLG_SECTOR_COUNT):
        offset = (slot * FRLG_SECTOR_COUNT + sector_index) * FRLG_SECTOR_SIZE
        block = data[offset:offset + FRLG_SECTOR_SIZE]
        if len(block) != FRLG_SECTOR_SIZE:
            return None
        section_id, checksum, magic, counter = struct.unpack_from("<HHII", block, 0xFF4)
        if (section_id >= FRLG_SECTOR_COUNT or section_id in sections or
                magic != FRLG_SAVE_MAGIC):
            return None
        payload = block[:FRLG_SECTION_LENGTHS[section_id]]
        if _frlg_checksum(payload) != checksum:
            return None
        sections[section_id] = payload
        sector_offsets[section_id] = offset
        counters.add(counter)
    if len(sections) != FRLG_SECTOR_COUNT or len(counters) != 1:
        return None
    return dict(slot=slot, counter=counters.pop(), sections=sections,
                sectorOffsets=sector_offsets)


def _frlg_hall_of_fame(data, game_clear):
    """Decode FireRed's separately checksummed Hall of Fame sectors.

    Unlike normal save sectors, the HOF writer stores the payload checksum in
    the footer's ``id`` field. The regular ``checksum`` and ``counter`` fields
    are left at zero, so these sectors must not be validated as slot sections.
    """
    sectors = {}
    for physical_index in FRLG_HOF_SECTOR_IDS:
        offset = physical_index * FRLG_SECTOR_SIZE
        block = data[offset:offset + FRLG_SECTOR_SIZE]
        if len(block) != FRLG_SECTOR_SIZE:
            continue
        payload = block[:FRLG_SECTOR_DATA_SIZE]
        payload_checksum, _unused_checksum, magic, _counter = struct.unpack_from(
            "<HHII", block, 0xFF4)
        if (magic != FRLG_SAVE_MAGIC or
                _frlg_checksum(payload) != payload_checksum):
            continue
        sectors[physical_index] = payload

    if set(sectors) != set(FRLG_HOF_SECTOR_IDS):
        if game_clear:
            return dict(state="unknown", count=None, entries=[],
                        reason="Setores do Hall da Fama ausentes ou inválidos.")
        return dict(state="supported", count=0, entries=[])

    payload = b"".join(sectors[index] for index in FRLG_HOF_SECTOR_IDS)
    entries = []
    invalid_entries = 0
    names = pokemon.CATALOG["names"]
    for team_index in range(FRLG_HOF_TEAM_COUNT):
        team_offset = team_index * FRLG_HOF_TEAM_SIZE
        first_species = _u16(payload, team_offset + 8) & 0x1FF
        if first_species == 0:
            break
        members = []
        for member_index in range(6):
            offset = team_offset + member_index * FRLG_HOF_MON_SIZE
            tid, personality = struct.unpack_from("<II", payload, offset)
            packed_species_level = _u16(payload, offset + 8)
            species = packed_species_level & 0x1FF
            level = packed_species_level >> 9
            if species == 0:
                continue
            if not 1 <= species <= FRLG_DEX_SPECIES_COUNT or not 1 <= level <= 100:
                invalid_entries += 1
                members = []
                break
            nickname = _decode_gen3_text(payload[offset + 10:offset + 20])
            members.append(dict(species=species,
                                name=names[species] if species < len(names) else f"Species {species}",
                                nickname=nickname or (names[species] if species < len(names) else f"Species {species}"),
                                level=level, trainerId=tid & 0xFFFF,
                                personality=personality,
                                nature=FRLG_NATURE_NAMES[personality % len(FRLG_NATURE_NAMES)]))
        if members:
            entries.append(dict(index=team_index + 1, pokemon=members))

    return dict(state="supported" if not invalid_entries else "partial",
                count=len(entries), entries=entries, invalidEntries=invalid_entries)


def _frlg_has_signature(data):
    if len(data) < FRLG_SECTOR_SIZE:
        return False
    return any(_u32(data, offset + 0xFF8) == FRLG_SAVE_MAGIC
               for offset in range(0, len(data) - FRLG_SECTOR_SIZE + 1,
                                   FRLG_SECTOR_SIZE))


def _looks_like_frlg(data, filename=""):
    data = bytes(data)
    if len(data) == FRLG_SIZE and any(_frlg_slot(data, slot) is not None
                                      for slot in range(FRLG_SLOT_COUNT)):
        return True
    if _frlg_has_signature(data):
        return True
    return _filename_says_frlg(filename)


def _newer_frlg_counter(left, right):
    difference = (left - right) & 0xFFFFFFFF
    return difference != 0 and difference < 0x80000000


def _decode_gen3_text(data):
    """Decode the Latin/digit subset used in international Gen III saves."""
    result = []
    for value in data:
        if value == 0xFF:
            break
        if 0xA1 <= value <= 0xAA:
            result.append(chr(ord("0") + value - 0xA1))
        elif 0xBB <= value <= 0xD4:
            result.append(chr(ord("A") + value - 0xBB))
        elif 0xD5 <= value <= 0xEE:
            result.append(chr(ord("a") + value - 0xD5))
        else:
            result.append({
                0xAB: "!", 0xAC: "?", 0xAD: ".", 0xAE: "-",
                0xAF: "·", 0xB0: "…", 0xB1: "“", 0xB2: "”",
                0xB3: "‘", 0xB4: "’", 0xB5: "♂", 0xB6: "♀",
                0xB7: "$", 0xB8: ",", 0xB9: "×", 0xBA: "/",
                0x00: " ",
            }.get(value, "�"))
    return "".join(result).strip()


def _frlg_flag(save_block1, flag_id):
    offset = FRLG_SAVE_BLOCK1_FLAGS_OFFSET + flag_id // 8
    if offset >= len(save_block1):
        return None
    return bool(save_block1[offset] & (1 << (flag_id & 7)))


def _frlg_record_offset(slot, logical_offset):
    """Translate a reconstructed SaveBlock offset back to its dump sector."""
    if logical_offset < FRLG_SAVE_BLOCK1_SIZE:
        section_id = 1 + logical_offset // FRLG_SECTOR_DATA_SIZE
        local_offset = logical_offset % FRLG_SECTOR_DATA_SIZE
        return slot["sectorOffsets"][section_id] + local_offset
    storage_offset = logical_offset - FRLG_SAVE_BLOCK1_SIZE
    section_id = 5 + storage_offset // FRLG_SECTOR_DATA_SIZE
    local_offset = storage_offset % FRLG_SECTOR_DATA_SIZE
    return slot["sectorOffsets"][section_id] + local_offset


def _crc16_ccitt(data):
    top = bot = 0xFF
    for byte in data:
        value = byte ^ top
        value ^= value >> 4
        top = (bot ^ (value >> 3) ^ (value << 4)) & 0xFF
        bot = (value ^ (value << 5)) & 0xFF
    return (top << 8) | bot


def _compare_counters(left, right):
    same = 2
    if left == 0xFFFFFFFF and right != 0xFFFFFFFE:
        return 1
    if right == 0xFFFFFFFF and left != 0xFFFFFFFE:
        return 0
    if left > right:
        return 0
    if left < right:
        return 1
    return same


def _select_active_block(data, start, length, label, checksum_excluded=0x10):
    copies = []
    for partition in (0, PARTITION_SIZE):
        offset = partition + start
        block = data[offset:offset + length]
        if len(block) != length:
            raise InvalidRawSave(f"Bloco HGSS {label} incompleto.")
        footer = length - 0x14
        major = _u32(block, footer)
        minor = _u32(block, footer + 4)
        magic = _u32(block, length - 8)
        saved_crc = _u16(block, length - 2)
        actual_crc = _crc16_ccitt(block[:-checksum_excluded])
        copies.append(dict(partition=partition, block=block, major=major, minor=minor,
                           magic=magic, saved_crc=saved_crc, actual_crc=actual_crc,
                           checksum_valid=saved_crc == actual_crc))

    if all(item["major"] == item["minor"] == 0xFFFFFFFF for item in copies):
        raise InvalidRawSave(f"Nenhuma copia inicializada do bloco HGSS {label}.")
    selected = _compare_counters(copies[0]["major"], copies[1]["major"])
    if selected == 2:
        selected = _compare_counters(copies[0]["minor"], copies[1]["minor"])
    if selected == 2:
        selected = 0
    active = copies[selected]
    if active["magic"] not in SAVE_MAGIC:
        raise InvalidRawSave(f"Assinatura do bloco HGSS {label} invalida.")
    if not active["checksum_valid"]:
        raise InvalidRawSave(f"Checksum do bloco HGSS {label} ativo invalido.")
    return active, dict(
        active_partition=selected,
        major=active["major"],
        minor=active["minor"],
        magic=f"{active['magic']:08x}",
        active_checksum="valid",
        backup_checksum=("valid" if copies[1 - selected]["checksum_valid"] and
                         copies[1 - selected]["magic"] in SAVE_MAGIC else "invalid"),
    )


def _gen4_hall_of_fame(data, start, game_clear):
    """Read the 30 fixed-size Gen IV Hall of Fame records when initialized."""
    candidates = []
    for partition in (0, PARTITION_SIZE):
        block = data[partition + start:partition + start + GEN4_HOF_SIZE]
        if len(block) != GEN4_HOF_SIZE:
            continue
        magic = _u32(block, len(block) - 0x10)
        revision = _u32(block, len(block) - 0x0C)
        size = _u32(block, len(block) - 0x08)
        saved_crc = _u16(block, len(block) - 2)
        valid = (magic in SAVE_MAGIC and size == GEN4_HOF_SIZE - 0x10 and
                 saved_crc == _crc16_ccitt(block[:-2]))
        if valid:
            candidates.append(dict(partition=partition, block=block,
                                   revision=revision,
                                   saveIndex=_u32(block, len(block) - 0x14)))
    if not candidates:
        return dict(state="unknown" if game_clear else "supported",
                    count=None if game_clear else 0, entries=[],
                    **({"reason": "O bloco do Hall da Fama não foi inicializado ou não passou no checksum."}
                       if game_clear else {}))
    if len(candidates) == 1:
        active = candidates[0]
    else:
        first, second = candidates
        compared = _compare_counters(first["revision"], second["revision"])
        if compared == 2:
            compared = _compare_counters(first["saveIndex"], second["saveIndex"])
        active = candidates[1 if compared == 1 else 0]

    entries, invalid_entries = [], 0
    names = pokemon.CATALOG["names"]
    for entry_index in range(GEN4_HOF_ENTRY_COUNT):
        entry_offset = entry_index * GEN4_HOF_ENTRY_SIZE
        entry = active["block"][entry_offset:entry_offset + GEN4_HOF_ENTRY_SIZE]
        if len(entry) != GEN4_HOF_ENTRY_SIZE or not any(entry):
            continue
        members = []
        for member_index in range(6):
            offset = member_index * GEN4_HOF_TEAM_SIZE
            species = _u16(entry, offset)
            level = entry[offset + 2]
            if species == 0:
                continue
            if not 1 <= species <= DEX_SPECIES_COUNT or not 1 <= level <= 100:
                invalid_entries += 1
                members = []
                break
            pid = _u32(entry, offset + 4)
            tid, sid = _u16(entry, offset + 8), _u16(entry, offset + 10)
            name = names[species] if species < len(names) else f"Species {species}"
            nickname = _decode_gen4_text(entry[offset + 12:offset + 34])
            nature = FRLG_NATURE_NAMES[pid % len(FRLG_NATURE_NAMES)]
            shiny_value = tid ^ sid ^ (pid & 0xFFFF) ^ (pid >> 16)
            members.append(dict(species=species, name=name, nickname=nickname or name,
                                level=level, nature=nature, shiny=shiny_value < 8))
        if members:
            entries.append(dict(index=entry_index + 1, pokemon=members))
    return dict(state="partial" if invalid_entries else "supported",
                count=len(entries), entries=entries, invalidEntries=invalid_entries,
                activePartition=active["partition"] // PARTITION_SIZE,
                revision=active["revision"])


def _decode_gen4_text(data):
    """Decode the ASCII subset of the documented Gen IV international table."""
    chars = []
    for offset in range(0, len(data) - 1, 2):
        code = _u16(data, offset)
        if code in (0, 0xFFFF):
            break
        if 0x121 <= code <= 0x12A:
            chars.append(chr(ord("0") + code - 0x121))
        elif 0x12B <= code <= 0x144:
            chars.append(chr(ord("A") + code - 0x12B))
        elif 0x145 <= code <= 0x15E:
            chars.append(chr(ord("a") + code - 0x145))
        else:
            char = {
                0x1AB: "!", 0x1AC: "?", 0x1AD: ",", 0x1AE: ".",
                0x1B2: "‘", 0x1B3: "'", 0x1B4: "“", 0x1B5: "”",
                0x1B6: "„", 0x1B7: "«", 0x1B8: "»", 0x1B9: "(",
                0x1BA: ")", 0x1BB: "♂", 0x1BC: "♀", 0x1BD: "+",
                0x1BE: "-", 0x1BF: "*", 0x1C0: "#", 0x1C1: "=",
                0x1C2: "&", 0x1C3: "~", 0x1C4: ":", 0x1C5: ";",
                0x1D0: "@", 0x1D2: "%", 0x1DE: " ",
            }.get(code)
            if char is None:
                return None
            chars.append(char)
    return "".join(chars)


def _decrypt_pk4(record):
    """Decode and checksum the 136-byte stored Gen IV PK4 structure."""
    if len(record) != PK4_STORED_SIZE:
        return None
    if not any(record):
        return dict(occupied=False, valid=True)
    pid = _u32(record, 0)
    checksum = _u16(record, 6)
    block = bytearray(record[8:PK4_STORED_SIZE])
    if (sum(struct.unpack_from("<64H", block)) & 0xFFFF) != checksum:
        seed = checksum
        for offset in range(0, len(block), 2):
            seed = (seed * 0x41C64E6D + 0x6073) & 0xFFFFFFFF
            value = _u16(block, offset) ^ (seed >> 16)
            struct.pack_into("<H", block, offset, value)
        order_start = ((pid >> 13) & 31) % 24 * 4
        order = pokemon.CATALOG["blockPositions"][order_start:order_start + 4]
        raw = bytes(block)
        block = bytearray().join(raw[index * 32:(index + 1) * 32] for index in order)
    if (sum(struct.unpack_from("<64H", block)) & 0xFFFF) != checksum:
        return dict(occupied=True, valid=False)
    decrypted = record[:8] + bytes(block)
    species = _u16(decrypted, 8)
    if not 1 <= species <= DEX_SPECIES_COUNT:
        return dict(occupied=True, valid=False)
    tid, sid = _u16(decrypted, 12), _u16(decrypted, 14)
    # PK4 layout: OT text at 0x68..0x75, met date at 0x7B..0x7D,
    # and extended met location at 0x46. These stable fields help keep
    # observations distinct without using nickname or species alone.
    trainer_name_raw = decrypted[0x68:0x76]
    stable_provenance = decrypted[0x7B:0x7E] + decrypted[0x46:0x48]
    identity = hashlib.sha256(
        struct.pack("<IHHH", pid, species, tid, sid) + trainer_name_raw + stable_provenance
    ).hexdigest()
    form = decrypted[0x40] >> 3
    ot_name = _decode_gen4_text(trainer_name_raw)
    return dict(occupied=True, valid=True, pid=pid, species=species,
                species_name=pokemon.CATALOG["names"][species], tid=tid, sid=sid,
                form=form, original_trainer=ot_name, identity_key=identity)


def _field(value, state="supported", source="active save block"):
    return dict(state=state, value=value, source=source)


class SinnohSaveParser(GameSaveParser):
    """Read Diamond, Pearl and Platinum 512 KiB raw save dumps."""

    LAYOUTS = {
        "DP": dict(game_size=GEN4_DP_GENERAL_SIZE, storage_size=GEN4_DP_STORAGE_SIZE,
                   trainer=GEN4_DP_TRAINER_OFFSET, party=GEN4_DP_PARTY_OFFSET,
                   dex=GEN4_DP_DEX_OFFSET, regional_species=151, battle_points=0x65F8),
        "PT": dict(game_size=GEN4_PT_GENERAL_SIZE, storage_size=GEN4_PT_STORAGE_SIZE,
                   trainer=GEN4_PT_TRAINER_OFFSET, party=GEN4_PT_PARTY_OFFSET,
                   dex=GEN4_PT_DEX_OFFSET, regional_species=210, battle_points=0x7234),
    }

    def parse(self, data, source):
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("O parser espera bytes do save.")
        data = bytes(data)
        detected = GameDetector().detect(data, source.get("filename", ""), source.get("gameHint"))
        if detected.get("gameVersion") not in self.LAYOUTS:
            raise UnsupportedRawSave("Jogo não reconhecido como Diamond, Pearl ou Platinum.")
        if len(data) != GEN4_DP_SIZE:
            raise InvalidRawSave("Save Diamond/Pearl/Platinum truncado ou com tamanho inesperado; esperado 512 KiB.")

        version = detected["gameVersion"]
        layout = self.LAYOUTS[version]
        general, general_meta = _select_active_block(
            data, 0, layout["game_size"], "geral Sinnoh", checksum_excluded=0x14)
        storage_start = layout["game_size"]
        storage, storage_meta = _select_active_block(
            data, storage_start, layout["storage_size"], "boxes Sinnoh", checksum_excluded=0x14)
        g, s = general["block"], storage["block"]
        trainer_offset, party_offset = layout["trainer"], layout["party"]
        trainer_name = _decode_gen4_text(g[trainer_offset:trainer_offset + 16])
        trainer_gender = g[trainer_offset + 0x18]
        party_count = g[party_offset - 4]
        if party_count > 6:
            raise InvalidRawSave("Quantidade de Pokemon na party excede o limite da Geração IV.")
        hours = _u16(g, trainer_offset + 0x22)
        minutes, seconds = g[trainer_offset + 0x24], g[trainer_offset + 0x25]
        play_time_valid = minutes < 60 and seconds < 60
        money = _u32(g, trainer_offset + 0x14)
        money_field = _field(money) if money <= 999999 else _field(None, "unknown")

        party, boxes, pokemon_rows, invalid_records = [], [], [], []

        def read_mon(record, location, offset):
            decoded = _decrypt_pk4(record[:PK4_STORED_SIZE])
            if not decoded["occupied"]:
                return None
            row = dict(location=location, offset=offset,
                       status="supported" if decoded["valid"] else "unsupported")
            if not decoded["valid"]:
                invalid_records.append(dict(location=location, offset=offset,
                                            reason="PK4 checksum or species field invalid"))
                return row
            row.update({key: decoded[key] for key in
                        ("pid", "species", "species_name", "tid", "sid", "form",
                         "original_trainer", "identity_key")})
            pokemon_rows.append(row)
            return row

        for slot in range(party_count):
            relative = party_offset + slot * PK4_PARTY_SIZE
            absolute = general["partition"] + relative
            party.append(read_mon(g[relative:relative + PK4_STORED_SIZE],
                                  dict(area="party", slot=slot), absolute))

        box_data_size = BOX_SLOTS * PK4_STORED_SIZE
        box_name_start = 4 + BOX_COUNT * box_data_size
        for box in range(BOX_COUNT):
            entries = []
            name_start = box_name_start + box * 40
            box_name = _decode_gen4_text(s[name_start:name_start + 40])
            for slot in range(BOX_SLOTS):
                relative = 4 + box * box_data_size + slot * PK4_STORED_SIZE
                absolute = storage["partition"] + storage_start + relative
                row = read_mon(s[relative:relative + PK4_STORED_SIZE],
                               dict(area="box", box=box, slot=slot), absolute)
                entries.append(row)
            boxes.append(dict(index=box, name=box_name or f"Box {box + 1}", pokemon=entries))

        dex = g[layout["dex"]:]
        if len(dex) < 0x128:
            raise InvalidRawSave("Bloco da Pokédex Sinnoh incompleto.")
        seen, caught = [], []
        for species in range(1, DEX_SPECIES_COUNT + 1):
            bit = species - 1
            if dex[4 + (bit >> 3)] & (1 << (bit & 7)):
                caught.append(species)
            if dex[4 + 0x40 + (bit >> 3)] & (1 << (bit & 7)):
                seen.append(species)

        unown_start = 4 + 4 * 0x40 + 4 + 4
        raw_unown = dex[unown_start:unown_start + 0x1C]
        unown_values, unown_valid, terminated = [], len(raw_unown) == 0x1C, False
        for value in raw_unown:
            if value == 0xFF:
                terminated = True
                continue
            if terminated or value >= 28 or value in unown_values:
                unown_valid = False
                break
            unown_values.append(value)

        progress_flags = g[trainer_offset + 0x1D]
        national_dex = bool(progress_flags & 2)
        badge_bits = g[trainer_offset + 0x1A]
        badges = {"sinnoh": [dict(name=name, acquired=bool(badge_bits & (1 << index)))
                             for index, name in enumerate(SINNOH_BADGE_NAMES)]}
        game_clear = bool(progress_flags & 1)
        story = {"game_clear": _field(game_clear), "national_dex": _field(national_dex),
                 "sinnoh_champion": _field(game_clear),
                 "hall_of_fame": _field(None, "unsupported")}
        hall_of_fame = _gen4_hall_of_fame(data, 0x20000, game_clear)
        play_seconds = hours * 3600 + minutes * 60 + seconds if play_time_valid else None
        game = "Platinum" if version == "PT" else detected["game"]
        return dict(
            schemaVersion=1, generation=4, game=game, gameVersion=version,
            saveHash=source["sha256"], observedAt=datetime.now(timezone.utc).isoformat(),
            trainer={
                "name": (_field(trainer_name) if trainer_name is not None
                         else _field(None, "unsupported")),
                "trainerId": _field(_u16(g, trainer_offset + 0x10)),
                "secretId": _field(_u16(g, trainer_offset + 0x12)),
                "gender": _field({0: "male", 1: "female"}.get(trainer_gender)
                                  if trainer_gender in (0, 1) else None,
                                  "supported" if trainer_gender in (0, 1) else "unknown"),
                "money": money_field,
                "playTime": _field(dict(hours=hours, minutes=minutes, seconds=seconds,
                                        totalSeconds=play_seconds)
                                   if play_time_valid else None,
                                   "supported" if play_time_valid else "unknown"),
            },
            party=party, boxes=boxes, pokemon=pokemon_rows,
            pokedex=dict(seen=seen, caught=caught, seenCount=len(seen), caughtCount=len(caught),
                         nationalDex=national_dex, totalSpecies=(493 if national_dex else layout["regional_species"]),
                         regionalSpecies=layout["regional_species"],
                         regionName=None if national_dex else "Sinnoh"),
            badges=badges,
            collections=dict(unownForms=unown_values if unown_valid else [],
                             unownCount=len(unown_values) if unown_valid else None,
                             unownStatus="supported" if unown_valid else "unknown"),
            story=story,
            miscellany={"battlePoints": _field(_u16(g, layout["battle_points"]))},
            hallOfFame=hall_of_fame,
            rawMetadata=dict(
                source=dict(kind=source.get("kind", "raw_file"), locator=source.get("locator"),
                            sizeBytes=len(data), sha256=source["sha256"]),
                activeBlocks=dict(general=general_meta, storage=storage_meta),
                invalidPokemonRecords=invalid_records,
                parser="SinnohSaveParser", checksum="valid"),
        )


class HGSSSaveParser(GameSaveParser):
    """Read-only parser for raw HeartGold/SoulSilver 0x80000 save dumps."""

    def parse(self, data, source):
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("O parser espera bytes do save.")
        data = bytes(data)
        detected = GameDetector().detect(data)
        if detected["state"] != "candidate":
            raise UnsupportedRawSave("Jogo nao reconhecido como HeartGold ou SoulSilver.")
        if len(data) != HGSS_SIZE:
            raise InvalidRawSave("Save HGSS truncado ou com tamanho inesperado; esperado 512 KiB.")

        general, general_meta = _select_active_block(data, GENERAL_START, GENERAL_SIZE, "geral")
        storage, storage_meta = _select_active_block(data, STORAGE_START, STORAGE_SIZE, "boxes")
        version_code = general["block"][TRAINER_OFFSET + 0x1C]
        if version_code not in ROM_VERSIONS:
            raise InvalidRawSave("Versao HGSS ausente no bloco geral ativo.")
        g = general["block"]
        s = storage["block"]
        trainer_name = _decode_gen4_text(g[TRAINER_OFFSET:TRAINER_OFFSET + 16])
        trainer_gender = g[TRAINER_OFFSET + 0x18]
        party_count = g[PARTY_COUNT_OFFSET]
        if party_count > 6:
            raise InvalidRawSave("Quantidade de Pokemon na party excede o limite HGSS.")
        hours = _u16(g, TRAINER_OFFSET + 0x22)
        minutes = g[TRAINER_OFFSET + 0x24]
        seconds = g[TRAINER_OFFSET + 0x25]
        play_time_valid = minutes < 60 and seconds < 60
        money = _u32(g, TRAINER_OFFSET + 0x14)
        if money > 999999:
            money_field = _field(None, "unknown")
        else:
            money_field = _field(money)

        party = []
        pokemon_rows = []
        invalid_records = []

        def read_mon(record, location, offset):
            decoded = _decrypt_pk4(record[:PK4_STORED_SIZE])
            if not decoded["occupied"]:
                return None
            row = dict(location=location, offset=offset,
                       status="supported" if decoded["valid"] else "unsupported")
            if not decoded["valid"]:
                invalid_records.append(dict(location=location, offset=offset,
                                            reason="PK4 checksum or species field invalid"))
                return row
            row.update({key: decoded[key] for key in
                        ("pid", "species", "species_name", "tid", "sid", "form",
                         "original_trainer", "identity_key")})
            pokemon_rows.append(row)
            return row

        for slot in range(party_count):
            offset = general["partition"] + PARTY_OFFSET + slot * PK4_PARTY_SIZE
            party.append(read_mon(g[PARTY_OFFSET + slot * PK4_PARTY_SIZE:
                                   PARTY_OFFSET + slot * PK4_PARTY_SIZE + PK4_STORED_SIZE],
                                  dict(area="party", slot=slot), offset))

        boxes = []
        box_data_start = STORAGE_START
        for box in range(BOX_COUNT):
            entries = []
            box_names_start = 0x12008
            box_name = _decode_gen4_text(s[box_names_start + box * 40:
                                            box_names_start + (box + 1) * 40])
            for slot in range(BOX_SLOTS):
                relative = box * BOX_SIZE + slot * PK4_STORED_SIZE
                offset = storage["partition"] + box_data_start + relative
                record = s[relative:relative + PK4_STORED_SIZE]
                row = read_mon(record, dict(area="box", box=box, slot=slot), offset)
                entries.append(row)
            boxes.append(dict(index=box, name=box_name or f"Box {box + 1}", pokemon=entries))

        dex = g[DEX_OFFSET:]
        if len(dex) < 0x128:
            raise InvalidRawSave("Bloco da Pokedex HGSS incompleto.")
        seen = []
        caught = []
        for species in range(1, DEX_SPECIES_COUNT + 1):
            bit = species - 1
            caught_offset = 4 + (bit >> 3)
            seen_offset = 4 + 0x40 + (bit >> 3)
            if dex[caught_offset] & (1 << (bit & 7)):
                caught.append(species)
            if dex[seen_offset] & (1 << (bit & 7)):
                seen.append(species)
        unown_start = 4 + 4 * 0x40 + 4 + 4
        raw_unown = dex[unown_start:unown_start + 0x1C]
        unown_values = []
        unown_valid = len(raw_unown) == 0x1C
        terminated = False
        for value in raw_unown:
            if value == 0xFF:
                terminated = True
                continue
            if terminated or value >= 28 or value in unown_values:
                unown_valid = False
                break
            unown_values.append(value)

        progress_flags = g[TRAINER_OFFSET + 0x1D]
        map_state = (g[0xBAE7] >> 3) & 3
        johto_badge_bits = g[TRAINER_OFFSET + 0x1A]
        kanto_badge_bits = g[TRAINER_OFFSET + 0x1F]
        badges = {
            region: [dict(name=name, acquired=bool(bits & (1 << index)))
                          for index, name in enumerate(BADGE_NAMES[region])]
            for region, bits in (("johto", johto_badge_bits), ("kanto", kanto_badge_bits))
        }
        story = {
            "johto_champion": _field(bool(progress_flags & 1)),
            "national_dex": _field(bool(progress_flags & 2)),
            "kanto_unlocked": (_field(map_state == 2) if map_state != 3
                               else _field(None, "unknown")),
            "red_defeated": _field(None, "unknown"),
            "story_flags": _field(None, "unsupported"),
            "hall_of_fame": _field(None, "unsupported"),
            "battle_frontier": _field(dict(bp=_u16(g, 0x5BB8)), "partial"),
            "pokeathlon": _field(None, "unsupported"),
        }
        hall_of_fame = _gen4_hall_of_fame(data, 0x23000, bool(progress_flags & 1))
        play_seconds = hours * 3600 + minutes * 60 + seconds if play_time_valid else None
        return dict(
            schemaVersion=1,
            game=ROM_VERSIONS[version_code],
            gameVersion="HG" if version_code == 0x47 else "SS",
            saveHash=source["sha256"],
            observedAt=datetime.now(timezone.utc).isoformat(),
            trainer={
                "name": _field(trainer_name) if trainer_name is not None else _field(None, "unsupported"),
                "trainerId": _field(_u16(g, TRAINER_OFFSET + 0x10)),
                "secretId": _field(_u16(g, TRAINER_OFFSET + 0x12)),
                "gender": _field({0: "male", 1: "female"}.get(trainer_gender)
                                  if trainer_gender in (0, 1) else None,
                                  "supported" if trainer_gender in (0, 1) else "unknown"),
                "money": money_field,
                "playTime": _field(dict(hours=hours, minutes=minutes, seconds=seconds,
                                        totalSeconds=play_seconds)
                                   if play_time_valid else None,
                                   "supported" if play_time_valid else "unknown"),
            },
            party=party,
            boxes=boxes,
            pokemon=pokemon_rows,
            pokedex=dict(seen=seen, caught=caught, seenCount=len(seen), caughtCount=len(caught),
                         nationalDex=bool(progress_flags & 2),
                         totalSpecies=(493 if progress_flags & 2 else 256),
                         regionalSpecies=256,
                         regionName=None if progress_flags & 2 else "Johto"),
            badges=badges,
            collections=dict(unownForms=unown_values if unown_valid else [],
                             unownCount=len(unown_values) if unown_valid else None,
                             unownStatus="supported" if unown_valid else "unknown"),
            story=story,
            miscellany={"battlePoints": _field(_u16(g, 0x5BB8))},
            hallOfFame=hall_of_fame,
            rawMetadata=dict(
                source=dict(kind=source.get("kind", "raw_file"), locator=source.get("locator"),
                            sizeBytes=len(data), sha256=source["sha256"]),
                activeBlocks=dict(general=general_meta, storage=storage_meta),
                invalidPokemonRecords=invalid_records,
                parser="HGSSSaveParser",
                checksum="valid",
            ),
        )


class FireRedSaveParser(GameSaveParser):
    """Read-only parser for raw 128 KiB FireRed/LeafGreen save dumps."""

    def parse(self, data, source):
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("O parser espera bytes do save.")
        data = bytes(data)
        filename = source.get("filename", "")
        if len(data) != FRLG_SIZE:
            if _frlg_has_signature(data) or _filename_says_frlg(filename):
                raise InvalidRawSave("Save FireRed/LeafGreen truncado ou com tamanho inesperado; esperado 128 KiB.")
            raise UnsupportedRawSave("Formato FireRed/LeafGreen esperado: dump bruto de 128 KiB.")
        if data and all(value == 0xFF for value in data):
            raise InvalidRawSave("O arquivo FireRed de 128 KiB está vazio (todos os bytes são FF). Selecione uma cópia real do save.")

        slots = [slot for index in range(FRLG_SLOT_COUNT)
                 if (slot := _frlg_slot(data, index)) is not None]
        if not slots:
            if _frlg_has_signature(data) or _filename_says_frlg(filename):
                raise InvalidRawSave("Nenhum slot FireRed/LeafGreen completo com setores e checksums válidos foi encontrado.")
            raise UnsupportedRawSave("Save nao reconhecido como FireRed/LeafGreen.")
        active = slots[0]
        for candidate in slots[1:]:
            if _newer_frlg_counter(candidate["counter"], active["counter"]):
                active = candidate

        sections = active["sections"]
        save_block2 = sections[0]
        save_block1 = b"".join(sections[index] for index in range(1, 5))
        storage = b"".join(sections[index] for index in range(5, 14))
        if len(save_block1) != FRLG_SAVE_BLOCK1_SIZE or len(storage) < FRLG_STORAGE_SIZE:
            raise InvalidRawSave("Os blocos FireRed/LeafGreen estão incompletos.")

        party_count = save_block1[0x34]
        if party_count > 6:
            raise InvalidRawSave("Quantidade de Pokemon na party FireRed excede seis.")
        current_box = storage[0]
        if current_box >= FRLG_BOX_COUNT:
            raise InvalidRawSave("A box ativa do save FireRed está fora do intervalo esperado.")
        box_data_offset = _frlg_box_data_offset(storage)

        pokemon_rows, invalid_records = [], []

        def read_mon(record, location, file_offset):
            decoded = _decrypt_pk3(record[:PK3_STORED_SIZE])
            if not decoded["occupied"]:
                return None
            row = dict(location=location, offset=file_offset,
                       status="supported" if decoded["valid"] else "unsupported")
            if not decoded["valid"]:
                invalid_records.append(dict(location=location, offset=file_offset,
                                            reason="PK3 checksum or species field invalid"))
                return row
            row.update({key: decoded[key] for key in
                        ("pid", "species", "species_name", "tid", "sid", "form",
                         "original_trainer", "identity_key", "egg", "shiny")})
            pokemon_rows.append(row)
            return row

        party = []
        for index in range(party_count):
            logical_offset = 0x38 + index * PK3_PARTY_SIZE
            record = save_block1[logical_offset:logical_offset + PK3_PARTY_SIZE]
            party.append(read_mon(record, dict(area="party", slot=index),
                                  _frlg_record_offset(active, logical_offset)))

        boxes = []
        for box_index in range(FRLG_BOX_COUNT):
            entries = []
            for slot_index in range(FRLG_BOX_SLOTS):
                storage_offset = box_data_offset + (box_index * FRLG_BOX_SLOTS + slot_index) * PK3_STORED_SIZE
                record = storage[storage_offset:storage_offset + PK3_STORED_SIZE]
                logical_offset = FRLG_SAVE_BLOCK1_SIZE + storage_offset
                entries.append(read_mon(record,
                                        dict(area="box", box=box_index, slot=slot_index),
                                        _frlg_record_offset(active, logical_offset)))
            name_offset = FRLG_BOX_NAMES_OFFSET + box_index * 9
            name = _decode_gen3_text(storage[name_offset:name_offset + 8])
            boxes.append(dict(index=box_index, name=name or f"Box {box_index + 1}",
                              pokemon=entries))

        caught, seen = [], []
        for species in range(1, FRLG_DEX_SPECIES_COUNT + 1):
            bit = species - 1
            if save_block2[FRLG_DEX_OWNED_OFFSET + (bit >> 3)] & (1 << (bit & 7)):
                caught.append(species)
            if save_block2[FRLG_DEX_SEEN_OFFSET + (bit >> 3)] & (1 << (bit & 7)):
                seen.append(species)

        national_flag = _frlg_flag(save_block1, FRLG_NATIONAL_DEX_FLAG)
        national_magic = save_block2[FRLG_POKEDEX_OFFSET + 3]
        national_var_offset = FRLG_SAVE_BLOCK1_VARS_OFFSET + (0x404E - 0x4000) * 2
        national_var = _u16(save_block1, national_var_offset)
        if national_flag and national_magic == 0xB9 and national_var == 0x6258:
            national_field = _field(True, source="FireRed national-dex flag, marker and variable")
        elif not national_flag and national_magic == 0 and national_var == 0:
            national_field = _field(False, source="FireRed national-dex flag, marker and variable")
        else:
            national_field = _field(None, "unknown", "Inconsistent FireRed national-dex markers")

        trainer_id = _u32(save_block2, FRLG_TRAINER_ID_OFFSET)
        tid, sid = trainer_id & 0xFFFF, trainer_id >> 16
        gender_value = save_block2[FRLG_TRAINER_GENDER_OFFSET]
        hours = _u16(save_block2, FRLG_PLAY_TIME_OFFSET)
        minutes = save_block2[FRLG_PLAY_TIME_OFFSET + 2]
        seconds = save_block2[FRLG_PLAY_TIME_OFFSET + 3]
        play_valid = minutes < 60 and seconds < 60
        money = _u32(save_block1, FRLG_MONEY_OFFSET) ^ _u32(save_block2, FRLG_ENCRYPTION_KEY_OFFSET)
        money_field = _field(money) if money <= 999999 else _field(None, "unknown")
        badges = {"kanto": [dict(name=name,
                                  acquired=bool(_frlg_flag(save_block1,
                                                          FRLG_BADGE_FLAG_START + index)))
                             for index, name in enumerate(FRLG_BADGE_NAMES)]}

        def flag_field(flag_id):
            value = _frlg_flag(save_block1, flag_id)
            return _field(value) if value is not None else _field(None, "unknown")

        story = {
            "game_clear": flag_field(FRLG_GAME_CLEAR_FLAG),
            "pokedex_received": flag_field(FRLG_POKEDEX_FLAG),
            "national_dex": national_field,
            "sevii_islands_1_3": flag_field(FRLG_SEVII_123_FLAG),
            "sevii_islands_4_7": flag_field(FRLG_SEVII_4567_FLAG),
            "lostelle_rescued": flag_field(FRLG_LOSTELLE_RESCUED_FLAG),
            "sevii_detour_finished": flag_field(FRLG_SEVII_DETOUR_FINISHED_FLAG),
            "rocket_warehouse_cleared": flag_field(FRLG_ROCKET_WAREHOUSE_CLEARED_FLAG),
            "ruby_recovered": flag_field(FRLG_RUBY_RECOVERED_FLAG),
            "sapphire_recovered": flag_field(FRLG_SAPPHIRE_RECOVERED_FLAG),
            "tanoby_ruins_unlocked": flag_field(FRLG_TANOBY_RUINS_FLAG),
        }
        trainer_records = [
            {**record, "defeated": bool(_frlg_flag(
                save_block1, FRLG_TRAINER_FLAG_START + record["trainerId"]))}
            for record in FRLG_TRAINER_RECORDS]
        defeated_trainers = sum(record["defeated"] for record in trainer_records)
        hidden_items = []
        for record in FRLG_HIDDEN_ITEM_RECORDS:
            flag_set = bool(_frlg_flag(save_block1, record["flagId"]))
            hidden_items.append({**record, "flagSet": flag_set,
                                 "found": flag_set if not record["renewable"] else None,
                                 "available": not flag_set if record["renewable"] else None})
        permanent_items = [item for item in hidden_items if not item["renewable"]]
        renewable_items = [item for item in hidden_items if item["renewable"]]
        miscellany = dict(
            trainerBattles=dict(state="supported", defeated=defeated_trainers,
                                total=len(trainer_records), items=trainer_records),
            hiddenItems=dict(state="supported",
                             found=sum(item["found"] for item in permanent_items),
                             total=len(permanent_items),
                             renewableAvailable=sum(item["available"] for item in renewable_items),
                             renewableTotal=len(renewable_items), items=hidden_items))
        hall_of_fame = _frlg_hall_of_fame(data, story["game_clear"]["value"] is True)
        fame_checker = []
        for index, person in enumerate(FRLG_FAME_CHECKER_PEOPLE):
            flags = (_u16(save_block1, FRLG_FAME_CHECKER_OFFSET + index * 2) >> 2) & 0x3F
            fame_checker.append(dict(person=person,
                                     facts=[bool(flags & (1 << fact)) for fact in range(6)]))
        trainer_tower = []
        for index, mode in enumerate(FRLG_TRAINER_TOWER_MODES):
            offset = FRLG_TRAINER_TOWER_OFFSET + index * 12
            trainer_tower.append(dict(mode=mode,
                                      floorsCleared=save_block1[offset + 8],
                                      receivedPrize=bool(save_block1[offset + 10] & 1)))
        minigames = dict(
            pokemonJump=dict(jumpsInRow=_u16(save_block2, FRLG_POKEMON_JUMP_OFFSET),
                             bestJumpScore=_u32(save_block2, FRLG_POKEMON_JUMP_OFFSET + 12)),
            dodrioBerryPicking=dict(
                berriesPicked=_u16(save_block2, FRLG_DODRIO_BERRY_PICK_OFFSET + 4),
                berriesPickedInRow=_u16(save_block2, FRLG_DODRIO_BERRY_PICK_OFFSET + 6),
                bestScore=_u32(save_block2, FRLG_DODRIO_BERRY_PICK_OFFSET)),
        )
        completion_data = dict(fameChecker=fame_checker, trainerTower=trainer_tower,
                               minigames=minigames)
        play_seconds = hours * 3600 + minutes * 60 + seconds if play_valid else None
        game_name = _frlg_game_name(filename, source.get("gameHint"))
        return dict(
            schemaVersion=3,
            game=game_name,
            gameVersion=("FR" if game_name == "FireRed" else
                         "LG" if game_name == "LeafGreen" else "FRLG"),
            saveHash=source["sha256"],
            observedAt=datetime.now(timezone.utc).isoformat(),
            trainer={
                "name": _field(_decode_gen3_text(save_block2[FRLG_PLAYER_NAME_OFFSET:
                                                              FRLG_PLAYER_NAME_OFFSET + 7])),
                "trainerId": _field(tid),
                "secretId": _field(sid),
                "gender": _field({0: "male", 1: "female"}.get(gender_value)
                                  if gender_value in (0, 1) else None,
                                  "supported" if gender_value in (0, 1) else "unknown"),
                "money": money_field,
                "playTime": _field(dict(hours=hours, minutes=minutes, seconds=seconds,
                                        totalSeconds=play_seconds)
                                   if play_valid else None,
                                   "supported" if play_valid else "unknown"),
            },
            party=party,
            boxes=boxes,
            pokemon=pokemon_rows,
            pokedex=dict(seen=seen, caught=caught, seenCount=len(seen), caughtCount=len(caught),
                         nationalDex=national_field["value"], totalSpecies=FRLG_DEX_SPECIES_COUNT,
                         regionalSpecies=FRLG_KANTO_DEX_SPECIES_COUNT),
            badges=badges,
            collections=dict(unownForms=[], unownCount=None, unownStatus="unsupported"),
            story=story,
            completionData=completion_data,
            miscellany=miscellany,
            hallOfFame=hall_of_fame,
            rawMetadata=dict(
                source=dict(kind=source.get("kind", "raw_file"), locator=source.get("locator"),
                            sizeBytes=len(data), sha256=source["sha256"]),
                activeSlot=active["slot"], saveCounter=active["counter"],
                sectorChecksums="valid", currentBox=current_box,
                boxDataOffset=box_data_offset,
                invalidPokemonRecords=invalid_records,
                parser="FireRedSaveParser", checksum="valid"),
        )


class RubySapphireEmeraldSaveParser(GameSaveParser):
    """Read Ruby, Sapphire, and Emerald's native 128 KiB Gen III saves."""

    @staticmethod
    def _flag(save_block1, layout, flag_id):
        offset = layout["flagsOffset"] + flag_id // 8
        if offset >= len(save_block1):
            return None
        return bool(save_block1[offset] & (1 << (flag_id & 7)))

    @staticmethod
    def _record_offset(slot, block1_size, logical_offset):
        if logical_offset < block1_size:
            section_id = 1 + logical_offset // GEN3_SECTOR_DATA_SIZE
            local_offset = logical_offset % GEN3_SECTOR_DATA_SIZE
        else:
            storage_offset = logical_offset - block1_size
            section_id = 5 + storage_offset // GEN3_SECTOR_DATA_SIZE
            local_offset = storage_offset % GEN3_SECTOR_DATA_SIZE
        return slot["sectorOffsets"][section_id] + local_offset

    def parse(self, data, source):
        if not isinstance(data, (bytes, bytearray)):
            raise TypeError("O parser espera bytes do save.")
        data = bytes(data)
        filename = source.get("filename", "")
        game_hint = source.get("gameHint")
        detected = _detect_gen3(data, filename, game_hint)
        if not detected or detected.get("variant") not in GEN3_LAYOUTS:
            if len(data) != FRLG_SIZE and _gen3_filename_variant(filename):
                raise InvalidRawSave("Save Ruby/Sapphire/Emerald truncado ou com tamanho inesperado; esperado 128 KiB.")
            raise UnsupportedRawSave("Formato Ruby, Sapphire ou Emerald esperado: dump bruto de 128 KiB.")
        variant = detected["variant"]
        layout = GEN3_LAYOUTS[variant]
        slots = detected.get("slots") or [slot for index in range(FRLG_SLOT_COUNT)
                                           if (slot := _gen3_slot(data, index, variant)) is not None]
        if not slots:
            raise InvalidRawSave(f"Nenhum slot {layout['game']} completo com setores e checksums válidos foi encontrado.")
        active = slots[0]
        for candidate in slots[1:]:
            if _newer_frlg_counter(candidate["counter"], active["counter"]):
                active = candidate

        sections = active["sections"]
        save_block2 = sections[0]
        save_block1 = b"".join(sections[index] for index in range(1, 5))
        storage = b"".join(sections[index] for index in range(5, 14))
        if (len(save_block1) != layout["block1Size"] or
                len(save_block2) != layout["block2Size"] or len(storage) < GEN3_STORAGE_SIZE):
            raise InvalidRawSave(f"Os blocos de {layout['game']} estão incompletos.")

        party_count = save_block1[layout["partyCount"]]
        if party_count > 6:
            raise InvalidRawSave("Quantidade de Pokémon na party excede seis.")
        current_box = storage[0]
        if current_box >= FRLG_BOX_COUNT:
            raise InvalidRawSave("A box ativa do save está fora do intervalo esperado.")
        box_data_offset = _frlg_box_data_offset(storage)
        pokemon_rows, invalid_records = [], []

        def read_mon(record, location, file_offset):
            decoded = _decrypt_pk3(record[:PK3_STORED_SIZE])
            if not decoded["occupied"]:
                return None
            row = dict(location=location, offset=file_offset,
                       status="supported" if decoded["valid"] else "unsupported")
            if not decoded["valid"]:
                invalid_records.append(dict(location=location, offset=file_offset,
                                            reason="PK3 checksum or species field invalid"))
                return row
            row.update({key: decoded[key] for key in
                        ("pid", "species", "species_name", "tid", "sid", "form",
                         "original_trainer", "identity_key", "egg", "shiny")})
            pokemon_rows.append(row)
            return row

        party = []
        for index in range(party_count):
            logical_offset = layout["party"] + index * PK3_PARTY_SIZE
            record = save_block1[logical_offset:logical_offset + PK3_PARTY_SIZE]
            party.append(read_mon(record, dict(area="party", slot=index),
                                  self._record_offset(active, layout["block1Size"], logical_offset)))
        boxes = []
        for box_index in range(FRLG_BOX_COUNT):
            entries = []
            for slot_index in range(FRLG_BOX_SLOTS):
                storage_offset = box_data_offset + (box_index * FRLG_BOX_SLOTS + slot_index) * PK3_STORED_SIZE
                record = storage[storage_offset:storage_offset + PK3_STORED_SIZE]
                logical_offset = layout["block1Size"] + storage_offset
                entries.append(read_mon(record, dict(area="box", box=box_index, slot=slot_index),
                                        self._record_offset(active, layout["block1Size"], logical_offset)))
            name_offset = FRLG_BOX_NAMES_OFFSET + box_index * 9
            name = _decode_gen3_text(storage[name_offset:name_offset + 8])
            boxes.append(dict(index=box_index, name=name or f"Box {box_index + 1}", pokemon=entries))

        caught, seen = [], []
        for species in range(1, FRLG_DEX_SPECIES_COUNT + 1):
            bit = species - 1
            if save_block2[FRLG_POKEDEX_OFFSET + 0x10 + (bit >> 3)] & (1 << (bit & 7)):
                caught.append(species)
            if save_block2[FRLG_POKEDEX_OFFSET + 0x44 + (bit >> 3)] & (1 << (bit & 7)):
                seen.append(species)

        def flag_field(flag_id):
            value = self._flag(save_block1, layout, flag_id)
            return _field(value) if value is not None else _field(None, "unknown")

        dex_flag = flag_field(layout["systemFlags"] + GEN3_NATIONAL_DEX_FLAG)
        national_magic = save_block2[FRLG_POKEDEX_OFFSET + 2]
        if dex_flag["value"] is True and national_magic == 0xDA:
            national_field = _field(True, source="Gen III National Dex system flag and Pokédex marker")
        elif dex_flag["value"] is False and national_magic != 0xDA:
            national_field = _field(False, source="Gen III National Dex system flag and Pokédex marker")
        else:
            national_field = _field(None, "unknown", "Inconsistent Gen III National Dex markers")

        trainer_id = _u32(save_block2, 0x0A)
        tid, sid = trainer_id & 0xFFFF, trainer_id >> 16
        gender_value = save_block2[0x08]
        hours, minutes, seconds = _u16(save_block2, 0x0E), save_block2[0x10], save_block2[0x11]
        play_valid = minutes < 60 and seconds < 60
        money = _u32(save_block1, layout["money"])
        if layout["encryptionKey"] is not None:
            money ^= _u32(save_block2, layout["encryptionKey"])
        money_field = _field(money) if money <= 999999 else _field(None, "unknown")

        badges = [dict(name=name, acquired=bool(self._flag(
            save_block1, layout, layout["systemFlags"] + GEN3_BADGE_FLAG_START + index)))
            for index, name in enumerate(GEN3_BADGE_NAMES)]
        story = {
            "pokedex_received": flag_field(layout["systemFlags"] + GEN3_POKEDEX_RECEIVED_FLAG),
            "game_clear": flag_field(layout["systemFlags"] + GEN3_GAME_CLEAR_FLAG),
            "national_dex": national_field,
            "regi_doors_opened": flag_field(0xE4),
            "frontier_unlocked": (flag_field(layout["systemFlags"] + 0x48)
                                  if variant == "E" else _field(None, "unsupported")),
        }
        rematch_bytes = save_block1[layout["rematches"]:
                                   layout["rematches"] + layout["rematchCount"]]
        rematches = [dict(trainerId=index + 1, active=value != 0, state=value)
                     for index, value in enumerate(rematch_bytes)]
        miscellany = dict(
            trainerRematches=dict(state="supported", activeCount=sum(row["active"] for row in rematches),
                                  total=len(rematches), items=rematches),
            hiddenItems=dict(state="unsupported", found=None, total=None, items=[]),
        )
        completion_data = {}
        if variant == "E":
            completion_data["minigames"] = dict(
                pokemonJump=dict(jumpsInRow=_u16(save_block2, 0x1FC),
                                 bestJumpScore=_u32(save_block2, 0x1FC + 12)),
                dodrioBerryPicking=dict(berriesPicked=_u16(save_block2, 0x20C + 4),
                                        berriesPickedInRow=_u16(save_block2, 0x20C + 6),
                                        bestScore=_u32(save_block2, 0x20C)),
            )
        hall_of_fame = _frlg_hall_of_fame(data, story["game_clear"]["value"] is True)
        play_seconds = hours * 3600 + minutes * 60 + seconds if play_valid else None
        game_name = _gen3_game_name(variant, filename, game_hint)
        source_record = dict(kind=source.get("kind", "raw_file"), locator=source.get("locator"),
                             sizeBytes=len(data), sha256=source["sha256"])
        return dict(
            schemaVersion=3, generation=3, game=game_name,
            gameVersion=("RS" if variant == "RS" else "E"),
            saveHash=source["sha256"], observedAt=datetime.now(timezone.utc).isoformat(),
            trainer={
                "name": _field(_decode_gen3_text(save_block2[0:7])),
                "trainerId": _field(tid), "secretId": _field(sid),
                "gender": _field({0: "male", 1: "female"}.get(gender_value)
                                  if gender_value in (0, 1) else None,
                                  "supported" if gender_value in (0, 1) else "unknown"),
                "money": money_field,
                "playTime": _field(dict(hours=hours, minutes=minutes, seconds=seconds,
                                        totalSeconds=play_seconds)
                                   if play_valid else None,
                                   "supported" if play_valid else "unknown"),
            },
            party=party, boxes=boxes, pokemon=pokemon_rows,
            pokedex=dict(seen=seen, caught=caught, seenCount=len(seen), caughtCount=len(caught),
                         nationalDex=national_field["value"], totalSpecies=FRLG_DEX_SPECIES_COUNT,
                         regionalSpecies=layout["regionalSpecies"],
                         regionName=(layout["region"] if national_field["value"] is not True else None)),
            badges={"hoenn": badges},
            collections=dict(unownForms=[], unownCount=None, unownStatus="unsupported"),
            story=story, completionData=completion_data, miscellany=miscellany,
            hallOfFame=hall_of_fame,
            supportedFeatures=["pokedex", "badges", "trainerId", "secretId", "gender", "money",
                               "playTime", "party", "boxes", "story", "trainerRematches",
                               "hallOfFame"] + (["minigames"] if variant == "E" else []),
            rawMetadata=dict(source=source_record, activeSlot=active["slot"],
                             saveCounter=active["counter"], sectorChecksums="valid",
                             currentBox=current_box, boxDataOffset=box_data_offset,
                             invalidPokemonRecords=invalid_records,
                             parser="RubySapphireEmeraldSaveParser", checksum="valid",
                             variant=variant),
        )


def _decrypt_pk3(record):
    """Decrypt and validate an encrypted 80-byte Gen III box Pokémon."""
    if len(record) != PK3_STORED_SIZE:
        return dict(occupied=False, valid=False)
    if not record[0x13] & 0x02:
        return dict(occupied=False, valid=True)
    pid, trainer_id = _u32(record, 0), _u32(record, 4)
    decrypted = bytearray(record)
    key = pid ^ trainer_id
    for offset in range(0x20, PK3_STORED_SIZE):
        decrypted[offset] ^= (key >> ((offset & 3) * 8)) & 0xFF
    order = pokemon.CATALOG["blockPositions"][(pid % 24) * 4:(pid % 24) * 4 + 4]
    encrypted_blocks = bytes(decrypted[0x20:0x50])
    for index, source_index in enumerate(order):
        decrypted[0x20 + index * 12:0x20 + (index + 1) * 12] = encrypted_blocks[
            source_index * 12:(source_index + 1) * 12]
    if (sum(struct.unpack_from("<24H", decrypted, 0x20)) & 0xFFFF) != _u16(record, 0x1C):
        return dict(occupied=True, valid=False)
    internal_species = _u16(decrypted, 0x20)
    if internal_species >= len(pokemon.CATALOG["g3ToSpecies"]):
        return dict(occupied=True, valid=False)
    species = pokemon.CATALOG["g3ToSpecies"][internal_species]
    egg = bool(_u32(decrypted, 0x48) >> 30 & 1) or internal_species == 0
    if not egg and not 1 <= species <= FRLG_DEX_SPECIES_COUNT:
        return dict(occupied=True, valid=False)
    tid, sid = trainer_id & 0xFFFF, trainer_id >> 16
    identity = hashlib.sha256(bytes(decrypted)).hexdigest()
    form = 0
    if species == 201:
        form = (((pid & 0x3000000) >> 18) | ((pid & 0x30000) >> 12) |
                ((pid & 0x300) >> 6) | (pid & 3)) % 28
    return dict(occupied=True, valid=True, pid=pid, species=species,
                species_name=pokemon.CATALOG["names"][species], tid=tid, sid=sid,
                form=form, egg=egg,
                shiny=(tid ^ sid ^ (pid & 0xFFFF) ^ (pid >> 16)) < 8,
                original_trainer=_decode_gen3_text(record[0x14:0x1B]),
                identity_key=identity)


def _frlg_box_data_offset(storage):
    """Choose a known FRLG box alignment by counting valid stored PK3 records."""
    scores = {}
    for start in FRLG_BOXES_OFFSETS:
        valid = 0
        for index in range(FRLG_BOX_COUNT * FRLG_BOX_SLOTS):
            offset = start + index * PK3_STORED_SIZE
            decoded = _decrypt_pk3(storage[offset:offset + PK3_STORED_SIZE])
            valid += decoded["occupied"] and decoded["valid"]
        scores[start] = valid
    # Prefer the upstream layout when both candidates are empty or tie.
    return max(FRLG_BOXES_OFFSETS, key=lambda offset: (scores[offset], offset == 0x0001))


class SnapshotComparator:
    """Pure comparison of two normalized HGSS snapshots."""

    @staticmethod
    def compare(before, after):
        if (before.get("gameVersion"), before.get("game")) != \
                (after.get("gameVersion"), after.get("game")):
            raise NativeSaveError("Snapshots de jogos diferentes nao podem ser comparados.")
        before_trainer = before.get("trainer", {})
        after_trainer = after.get("trainer", {})
        same_trainer = _trainer_key(before) == _trainer_key(after)
        if not same_trainer:
            raise NativeSaveError("Snapshots pertencem a treinadores diferentes.")
        def badge_set(snapshot):
            return {f"{region}:{badge['name']}" for region, rows in snapshot["badges"].items()
                    for badge in rows if badge["acquired"]}
        old_badges, new_badges = badge_set(before), badge_set(after)
        old_time = before_trainer.get("playTime", {}).get("value")
        new_time = after_trainer.get("playTime", {}).get("value")
        old_pokemon = Counter(mon["identity_key"] for mon in before.get("pokemon", []))
        new_pokemon = Counter(mon["identity_key"] for mon in after.get("pokemon", []))
        old_caught = set(before["pokedex"]["caught"])
        new_caught = set(after["pokedex"]["caught"])
        old_seen = set(before["pokedex"]["seen"])
        new_seen = set(after["pokedex"]["seen"])
        old_bp = before.get("story", {}).get("battle_frontier", {}).get("value")
        new_bp = after.get("story", {}).get("battle_frontier", {}).get("value")
        if isinstance(old_bp, dict):
            old_bp = old_bp.get("bp")
        if isinstance(new_bp, dict):
            new_bp = new_bp.get("bp")
        return dict(
            beforeHash=before["saveHash"], afterHash=after["saveHash"],
            badgeAdditions=sorted(new_badges - old_badges),
            badgeRemovals=sorted(old_badges - new_badges),
            caughtDelta=after["pokedex"]["caughtCount"] - before["pokedex"]["caughtCount"],
            caughtAdded=sorted(new_caught - old_caught),
            caughtRemoved=sorted(old_caught - new_caught),
            seenDelta=after["pokedex"]["seenCount"] - before["pokedex"]["seenCount"],
            seenAdded=sorted(new_seen - old_seen),
            seenRemoved=sorted(old_seen - new_seen),
            battlePointsDelta=(new_bp - old_bp if isinstance(old_bp, int) and
                               isinstance(new_bp, int) else None),
            unownDelta=(after["collections"]["unownCount"] -
                        before["collections"]["unownCount"]
                        if isinstance(after.get("collections", {}).get("unownCount"), int) and
                        isinstance(before.get("collections", {}).get("unownCount"), int) else None),
            playTimeDeltaSeconds=(new_time["totalSeconds"] - old_time["totalSeconds"]
                                  if old_time and new_time and old_time["totalSeconds"] is not None and
                                  new_time["totalSeconds"] is not None else None),
            newPokemon=sum(max(0, count - old_pokemon.get(key, 0))
                           for key, count in new_pokemon.items()),
            removedPokemon=sum(max(0, count - new_pokemon.get(key, 0))
                               for key, count in old_pokemon.items()),
            evidence="DIRECT_SNAPSHOT_COMPARISON",
        )


HGSS_COMPLETION_PROFILE = dict(
    id="hgss-observable-v1",
    name="HGSS observável",
    definition=["16 badges", "Johto League champion", "Kanto unlocked",
                "493 Pokédex caught flags", "28 Unown forms"],
    unsupported=["Red defeated"],
)
FIRERED_COMPLETION_PROFILE = dict(
    id="firered-observable-v2",
    name="FireRed observável",
    definition=["8 insígnias e 10 metas da história/Ilhas Sevii",
                "380 espécies capturáveis no perfil nacional (exclui 6 espécies de evento)",
                "96 pistas do Fame Checker", "4 modos da Trainer Tower concluídos",
                "Pokémon Jump: 200 saltos consecutivos", "Dodrio Berry Picking: 200 frutas"],
    caveat=("A porcentagem resume os 500 critérios desta aba; os registros opcionais "
            "de treinadores e itens ocultos ficam em Miscelânea."),
)
GEN3_COMPLETION_PROFILE = dict(
    id="gen3-observable-v1",
    name="Geração III observável",
    definition=["8 insígnias de Hoenn", "Liga Pokémon de Hoenn", "National Dex desbloqueada",
                "386 flags de capturado da Pokédex"],
    caveat=("A porcentagem cobre os flags visíveis neste save; conteúdo de eventos, "
            "Battle Frontier e itens ocultos não está totalmente modelado."),
)
GEN4_SINNOH_COMPLETION_PROFILE = dict(
    id="sinnoh-observable-v1",
    name="Geração IV · Sinnoh observável",
    definition=["8 insígnias de Sinnoh", "Liga Pokémon de Sinnoh",
                "Pokédex Nacional desbloqueada", "493 flags de capturado da Pokédex",
                "28 formas de Unown"],
    caveat=("O perfil mede os flags observáveis no save; eventos distribuídos e conteúdo "
            "adicional de pós-jogo não são uma confirmação de 100% do jogo."),
)


class CompletionTracker:
    """Explicitly configured completion criteria; unknown items stay excluded."""

    @staticmethod
    def evaluate(snapshot):
        criteria = []
        for region, rows in snapshot.get("badges", {}).items():
            for row in rows:
                criteria.append(dict(id=f"badge:{region}:{row['name']}",
                                     label=f"Insígnia {region.title()} — {row['name']}",
                                     state="complete" if row["acquired"] else "missing",
                                     group="badges"))
        story = snapshot.get("story", {})
        is_frlg = snapshot.get("gameVersion") in ("FR", "LG", "FRLG")
        is_gen3 = snapshot.get("gameVersion") in ("RS", "E")
        is_sinnoh = snapshot.get("gameVersion") in ("DP", "PT")
        if is_frlg:
            story_criteria = (
                ("game_clear", "Campeão da Liga Indigo"),
                ("national_dex", "Pokédex Nacional desbloqueada"),
                ("sevii_islands_1_3", "Ilhas Sevii 1–3 desbloqueadas"),
                ("sevii_islands_4_7", "Ilhas Sevii 4–7 desbloqueadas"),
                ("lostelle_rescued", "Lostelle resgatada"),
                ("sevii_detour_finished", "Desvio de Sevii concluído"),
                ("rocket_warehouse_cleared", "Armazém Rocket concluído"),
                ("ruby_recovered", "Ruby recuperada"),
                ("sapphire_recovered", "Sapphire recuperada"),
                ("tanoby_ruins_unlocked", "Ruínas Tanoby desbloqueadas"),
            )
            profile = FIRERED_COMPLETION_PROFILE
            dex_count = FRLG_DEX_SPECIES_COUNT
            dex_name = "Kanto"
            dex_species = [species for species in range(1, dex_count + 1)
                           if species not in FRLG_NATIONAL_DEX_EXCLUDED]
        elif is_gen3:
            story_criteria = (("game_clear", "Campeão da Liga de Hoenn"),
                              ("national_dex", "Pokédex Nacional desbloqueada"))
            profile = dict(GEN3_COMPLETION_PROFILE)
            if snapshot.get("gameVersion") == "E":
                story_criteria += (("frontier_unlocked", "Battle Frontier desbloqueada"),)
                profile.update(
                    id="emerald-observable-v1", name="Emerald observável",
                    definition=[*GEN3_COMPLETION_PROFILE["definition"],
                                "Battle Frontier desbloqueada",
                                "200 saltos consecutivos e 200 berries no Dodrio Berry Picking"])
            dex_count = FRLG_DEX_SPECIES_COUNT
            dex_name = ""
            dex_species = range(1, dex_count + 1)
        elif is_sinnoh:
            story_criteria = (("game_clear", "Campeão da Liga de Sinnoh"),
                              ("national_dex", "Pokédex Nacional desbloqueada"))
            profile = GEN4_SINNOH_COMPLETION_PROFILE
            dex_count = DEX_SPECIES_COUNT
            dex_name = "Sinnoh"
            dex_species = range(1, dex_count + 1)
        else:
            story_criteria = (("johto_champion", "Johto League champion"),
                              ("kanto_unlocked", "Kanto unlocked"))
            profile = HGSS_COMPLETION_PROFILE
            dex_count = DEX_SPECIES_COUNT
            dex_name = ""
            dex_species = range(1, dex_count + 1)
        for key, label in story_criteria:
            field = story.get(key, {})
            state = "unknown" if field.get("state") != "supported" else (
                "complete" if field.get("value") else "missing")
            criteria.append(dict(id=f"story:{key}", label=label, state=state,
                                 group="story"))
        caught_species = set(snapshot.get("pokedex", {}).get("caught", []))
        for species in dex_species:
            caught = species in caught_species
            criteria.append(dict(id=f"caught:{species}",
                                 label=f"{dex_name + ' ' if dex_name else ''}caught #{species} {pokemon.CATALOG['names'][species]}",
                                 state="complete" if caught else "missing",
                                 group="pokedex"))
        if is_frlg:
            completion_data = snapshot.get("completionData", {})
            fame_records = completion_data.get("fameChecker", [])
            fame_by_person = {row.get("person"): row for row in fame_records
                              if isinstance(row, dict)}
            for person in FRLG_FAME_CHECKER_PEOPLE:
                row = fame_by_person.get(person, {})
                facts = row.get("facts")
                for index in range(6):
                    known = isinstance(facts, list) and len(facts) == 6 and isinstance(facts[index], bool)
                    criteria.append(dict(
                        id=f"fame:{person.lower().replace(' ', '-') }:{index + 1}",
                        label=f"Fame Checker — {person}, pista {index + 1}",
                        state=("unknown" if not known else "complete" if facts[index] else "missing"),
                        group="fameChecker"))
            tower_rows = {row.get("mode"): row for row in completion_data.get("trainerTower", [])
                          if isinstance(row, dict)}
            for mode in FRLG_TRAINER_TOWER_MODES:
                row = tower_rows.get(mode, {})
                floors = row.get("floorsCleared")
                prize = row.get("receivedPrize")
                known = isinstance(floors, int) and 0 <= floors <= 8 and isinstance(prize, bool)
                criteria.append(dict(
                    id=f"trainer-tower:{mode.lower()}",
                    label=f"Trainer Tower — desafio {mode} concluído",
                    state=("unknown" if not known else
                           "complete" if prize or floors == 8 else "missing"),
                    group="trainerTower"))
            minigames = completion_data.get("minigames", {})
            jump = minigames.get("pokemonJump", {}).get("jumpsInRow")
            berries = minigames.get("dodrioBerryPicking", {}).get("berriesPicked")
            for key, label, value, target in (
                    ("pokemon-jump", "Pokémon Jump — 200 saltos consecutivos", jump, 200),
                    ("dodrio-berry-picking", "Dodrio Berry Picking — 200 frutas", berries, 200)):
                known = isinstance(value, int) and 0 <= value <= 0xFFFF
                criteria.append(dict(id=f"minigame:{key}", label=label,
                                     state=("unknown" if not known else
                                            "complete" if value >= target else "missing"),
                                     group="minigames"))
        elif is_gen3 and snapshot.get("gameVersion") == "E":
            minigames = snapshot.get("completionData", {}).get("minigames", {})
            jump = minigames.get("pokemonJump", {}).get("jumpsInRow")
            berries = minigames.get("dodrioBerryPicking", {}).get("berriesPicked")
            for key, label, value, target in (
                    ("pokemon-jump", "Pokémon Jump — 200 saltos consecutivos", jump, 200),
                    ("dodrio-berry-picking", "Dodrio Berry Picking — 200 frutas", berries, 200)):
                known = isinstance(value, int) and 0 <= value <= 0xFFFF
                criteria.append(dict(id=f"minigame:{key}", label=label,
                                     state=("unknown" if not known else
                                            "complete" if value >= target else "missing"),
                                     group="minigames"))
        collection = snapshot.get("collections", {})
        if not is_frlg and not is_gen3:
            forms = set(collection.get("unownForms", []))
            for form in range(28):
                criteria.append(dict(id=f"unown:{form}", label=f"Unown form {form + 1}",
                                     state=("unknown" if collection.get("unownStatus") != "supported"
                                            else "complete" if form in forms else "missing"),
                                     group="collections"))
        evaluated = [item for item in criteria if item["state"] != "unknown"]
        completed = sum(item["state"] == "complete" for item in evaluated)
        missing = [item for item in evaluated if item["state"] == "missing"]
        unknown = [item for item in criteria if item["state"] == "unknown"]
        total = len(evaluated)
        percent = round((completed * 100.0 / total), 1) if total else 0.0
        group_labels = {
            "badges": "Insígnias",
            "story": ("História de Hoenn" if is_gen3 else
                      "História de Sinnoh" if is_sinnoh else
                      "História e Ilhas Sevii" if is_frlg else "História de Johto"),
            "pokedex": "Capturas da Pokédex", "fameChecker": "Fame Checker",
            "trainerTower": "Trainer Tower", "minigames": "Minigames",
            "collections": "Coleções",
        }
        groups = []
        for group_id, label in group_labels.items():
            group_items = [item for item in criteria if item.get("group") == group_id]
            if not group_items:
                continue
            group_known = [item for item in group_items if item["state"] != "unknown"]
            groups.append(dict(
                id=group_id, label=label,
                completed=sum(item["state"] == "complete" for item in group_known),
                total=len(group_known),
                missing=sum(item["state"] == "missing" for item in group_known),
                unknown=sum(item["state"] == "unknown" for item in group_items),
            ))
        return dict(profile=profile, completed=completed, total=total,
                    percent=percent, completeWithinProfile=(not missing and not unknown),
                    game100PercentConfirmed=False,
                    groups=groups, missing=missing, unknown=unknown)


def _json_write_atomic(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(prefix=".native-saves-", dir=path.parent)
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, separators=(",", ":"))
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


class SnapshotRepository:
    """Storage for uploaded save copies and normalized snapshots."""

    def __init__(self, data_root):
        self.root = Path(data_root) / "native-saves"
        self.saves_dir = self.root / "saves"
        self.snapshots_dir = self.root / "snapshots"
        self.index_path = self.root / "index.json"
        self.manual_path = self.root / "journey-manual.json"
        self.lock = threading.RLock()
        self.parser = NativeSaveParser()
        self.saves_dir.mkdir(parents=True, exist_ok=True)
        self.snapshots_dir.mkdir(parents=True, exist_ok=True)
        self._reprocess_legacy_saves()

    def _read_index(self):
        try:
            data = json.loads(self.index_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return dict(version=1, saves=[])
        except (OSError, ValueError) as exc:
            raise SnapshotRepositoryError("Indice Native Saves invalido; os dados foram preservados.") from exc
        if (not isinstance(data, dict) or set(data) != {"version", "saves"} or
                data["version"] != 1 or not isinstance(data["saves"], list)):
            raise SnapshotRepositoryError("Indice Native Saves invalido; os dados foram preservados.")
        return data

    def _snapshot_path(self, digest):
        if (not isinstance(digest, str) or len(digest) != 64 or
                any(char not in "0123456789abcdef" for char in digest)):
            raise SnapshotRepositoryError("Hash de snapshot Native Saves invalido.")
        return self.snapshots_dir / f"{digest}.json"

    def import_file(self, path, filename=None):
        source = RawFileSaveSource(path)
        data, metadata = source.read()
        return self.import_bytes(data, filename=filename or self._name_from_path(path),
                                 locator=metadata["locator"], source_kind=metadata["kind"])

    def import_bytes(self, data, filename="save.bin", locator=None, source_kind="raw_file",
                     game_hint=None):
        if not isinstance(data, bytes) or not 0 < len(data) <= MAX_RAW_SAVE_BYTES:
            raise InvalidRawSave("O arquivo esta vazio ou excede 64 MiB.")
        digest = hashlib.sha256(data).hexdigest()
        filename = _safe_filename(filename or "save.bin")
        metadata = dict(kind=source_kind, locator=locator or filename, filename=filename,
                        sizeBytes=len(data), sha256=digest)
        if game_hint is not None:
            metadata["gameHint"] = str(game_hint)
        digest = metadata["sha256"]
        with self.lock:
            index = self._read_index()
            existing = next((row for row in index["saves"] if row["sha256"] == digest), None)
            if existing:
                if existing.get("state") == "supported":
                    return self.describe(digest)
                try:
                    snapshot = self.parser.parse(data, metadata)
                except UnsupportedRawSave:
                    return self.describe(digest)
                save_path = self.saves_dir / f"{digest}.sav"
                if save_path.exists() and hashlib.sha256(save_path.read_bytes()).hexdigest() != digest:
                    raise SnapshotRepositoryError("A copia Native Saves existente nao confere; preservada.")
                if not save_path.exists():
                    _write_bytes_new(save_path, data)
                self._prepare_snapshot(index, existing, snapshot)
                _json_write_atomic(self.index_path, index)
                return self.describe(digest)
            try:
                snapshot = self.parser.parse(data, metadata)
                state = "supported"
            except UnsupportedRawSave as exc:
                snapshot = None
                state = "unsupported"
                reason = str(exc)
            except InvalidRawSave:
                raise

            save_path = self.saves_dir / f"{digest}.sav"
            if save_path.exists():
                if hashlib.sha256(save_path.read_bytes()).hexdigest() != digest:
                    raise SnapshotRepositoryError("A copia Native Saves existente nao confere; preservada.")
            else:
                _write_bytes_new(save_path, data)

            row = dict(sha256=digest, filename=filename,
                       sizeBytes=len(data), importedAt=datetime_now(), state=state,
                       game=snapshot["game"] if snapshot else None,
                       gameVersion=snapshot["gameVersion"] if snapshot else None,
                       reason=None if snapshot else reason)
            if snapshot:
                self._prepare_snapshot(index, row, snapshot)
            index["saves"].append(row)
            _json_write_atomic(self.index_path, index)
            return self.describe(digest)

    def _prepare_snapshot(self, index, row, snapshot):
        digest = row["sha256"]
        previous = []
        if _trainer_identity_reliable(snapshot):
            for item in index["saves"]:
                if (item["sha256"] == digest or item.get("state") != "supported" or
                        (item.get("gameVersion"), item.get("game")) !=
                        (snapshot["gameVersion"], snapshot["game"])):
                    continue
                candidate = self._read_snapshot(item["sha256"])
                if (_trainer_identity_reliable(candidate) and
                        _trainer_key(candidate) == _trainer_key(snapshot)):
                    previous.append((item, candidate))
        previous_signatures = {mon["identity_key"] for _, candidate in previous
                               for mon in candidate.get("pokemon", [])}
        duplicates = Counter(mon["identity_key"] for mon in snapshot["pokemon"])
        trainer_seed = json.dumps(_trainer_key(snapshot), ensure_ascii=False)
        for mon in snapshot["pokemon"]:
            key = mon["identity_key"]
            duplicate = duplicates[key] > 1
            identity_seed = trainer_seed + ":" + key
            if duplicate:
                identity_seed += ":" + digest + ":" + str(mon["offset"])
            mon["chestLinkId"] = str(uuid.uuid5(_NAMESPACE, identity_seed))
            mon["identityStatus"] = ("INFERRED" if duplicate or key in previous_signatures
                                      else "OBSERVED")
            mon["observedAt"] = snapshot["observedAt"]
            mon["saveHash"] = digest
        row.update(state="supported", game=snapshot["game"],
                   gameVersion=snapshot["gameVersion"], reason=None,
                   pokemonCount=len(snapshot["pokemon"]), trainer=snapshot["trainer"])
        snapshot["sourceFilename"] = row["filename"]
        snapshot["comparison"] = (SnapshotComparator.compare(previous[-1][1], snapshot)
                                   if previous else None)
        _json_write_atomic(self._snapshot_path(digest), snapshot)

    def _reprocess_legacy_saves(self):
        """Reparse stored files after parser support expands, without touching their bytes."""
        with self.lock:
            index = self._read_index()
            changed = False
            for row in index["saves"]:
                if row.get("state") not in ("unsupported", "invalid"):
                    continue
                if row.get("sizeBytes") not in (GEN1_SIZE, GEN2_INT_SIZE, GEN2_JPN_SIZE,
                                                  FRLG_SIZE, HGSS_SIZE):
                    continue
                path = self.saves_dir / f"{row.get('sha256', '')}.sav"
                try:
                    data = path.read_bytes()
                except OSError:
                    continue
                digest = row.get("sha256")
                if hashlib.sha256(data).hexdigest() != digest:
                    raise SnapshotRepositoryError("A copia Native Saves existente nao confere; preservada.")
                detected = GameDetector().detect(data, row.get("filename", ""))
                if detected["state"] != "candidate":
                    continue
                source = dict(kind="stored_copy", locator=row.get("filename"),
                              filename=row.get("filename", "save.bin"),
                              sizeBytes=len(data), sha256=digest)
                try:
                    snapshot = self.parser.parse(data, source)
                except UnsupportedRawSave:
                    continue
                except InvalidRawSave as exc:
                    row.update(state="invalid", game=detected.get("game"),
                               gameVersion=detected.get("gameVersion"), reason=str(exc))
                    changed = True
                    continue
                self._prepare_snapshot(index, row, snapshot)
                changed = True
            if changed:
                _json_write_atomic(self.index_path, index)

    @staticmethod
    def _name_from_path(path):
        return Path(path).name

    @staticmethod
    def _safe_filename(name):
        return _safe_filename(name)

    def _read_snapshot(self, digest):
        try:
            value = json.loads(self._snapshot_path(digest).read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SnapshotRepositoryError("Snapshot Native Saves invalido; os dados foram preservados.") from exc
        if not isinstance(value, dict) or value.get("saveHash") != digest:
            raise SnapshotRepositoryError("Snapshot Native Saves inconsistente; os dados foram preservados.")
        return value

    def list_saves(self):
        with self.lock:
            rows = sorted(self._read_index()["saves"], key=lambda row: row["importedAt"], reverse=True)
            return rows

    def _read_manual_events(self):
        try:
            manual = json.loads(self.manual_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return []
        except (OSError, ValueError) as exc:
            raise SnapshotRepositoryError("Eventos Journey invalidos; os dados foram preservados.") from exc
        if not isinstance(manual, list) or any(
                not isinstance(item, dict) or
                set(item) != {"date", "label", "source", "status", "saveHash"} or
                item.get("source") != "MANUAL" for item in manual):
            raise SnapshotRepositoryError("Eventos Journey invalidos; os dados foram preservados.")
        return manual

    def delete_save(self, digest):
        """Remove an imported copy and its derived records for one save hash."""
        snapshot_path = self._snapshot_path(digest)
        with self.lock:
            index = self._read_index()
            row = next((item for item in index["saves"] if item.get("sha256") == digest), None)
            if row is None:
                raise SnapshotRepositoryError("Save Native Saves nao encontrado.")

            updated_index = dict(index, saves=[item for item in index["saves"]
                                               if item.get("sha256") != digest])
            original_manual = self._read_manual_events()
            updated_manual = [item for item in original_manual if item.get("saveHash") != digest]
            manual_exists = self.manual_path.exists()
            staged = []
            manual_written = False
            targets = (self.saves_dir / f"{digest}.sav", snapshot_path)
            try:
                for path in targets:
                    if path.exists() or path.is_symlink():
                        retired = path.with_name(f".{digest}-{uuid.uuid4().hex}.removed")
                        os.replace(path, retired)
                        staged.append((path, retired))
                if updated_manual != original_manual:
                    _json_write_atomic(self.manual_path, updated_manual)
                    manual_written = True
                _json_write_atomic(self.index_path, updated_index)
            except BaseException:
                if manual_written:
                    if manual_exists:
                        _json_write_atomic(self.manual_path, original_manual)
                    else:
                        self.manual_path.unlink(missing_ok=True)
                for path, retired in reversed(staged):
                    if retired.exists() or retired.is_symlink():
                        os.replace(retired, path)
                raise

            for _, retired in staged:
                try:
                    retired.unlink()
                except FileNotFoundError:
                    pass
            return dict(deleted=True, sha256=digest)

    def describe(self, digest):
        with self.lock:
            row = next((item for item in self._read_index()["saves"] if item["sha256"] == digest), None)
            if row is None:
                raise SnapshotRepositoryError("Save Native Saves nao encontrado.")
            result = dict(row)
            if row["state"] == "supported":
                snapshot = self._read_snapshot(digest)
                result["summary"] = dict(
                    partyCount=sum(mon is not None for mon in snapshot["party"]),
                    pokemonCount=len(snapshot["pokemon"]),
                    badges=sum(badge["acquired"] for region in snapshot["badges"].values()
                               for badge in region),
                    caught=snapshot["pokedex"]["caughtCount"],
                    seen=snapshot["pokedex"]["seenCount"],
                    playTime=snapshot["trainer"]["playTime"],
                )
            return result

    def snapshot(self, digest):
        with self.lock:
            snapshot = self._read_snapshot(digest)
            row = next((item for item in self._read_index()["saves"]
                        if item["sha256"] == digest), None)
            if row is None or row.get("state") != "supported":
                raise SnapshotRepositoryError("Save Native Saves nao encontrado.")
            completion = snapshot.get("completionData")
            completion_ready = (isinstance(completion, dict) and
                                {"fameChecker", "trainerTower", "minigames"} <= set(completion))
            miscellany = snapshot.get("miscellany")
            hidden_items = miscellany.get("hiddenItems") if isinstance(miscellany, dict) else None
            trainer_battles = miscellany.get("trainerBattles") if isinstance(miscellany, dict) else None
            frlg_sections_ready = (
                isinstance(hidden_items, dict) and
                {"found", "total", "renewableAvailable", "renewableTotal", "items"} <= set(hidden_items) and
                isinstance(trainer_battles, dict) and "items" in trainer_battles and
                isinstance(snapshot.get("hallOfFame"), dict))
            schema_version = snapshot.get("schemaVersion")
            frlg_schema_ready = isinstance(schema_version, int) and schema_version >= 3
            if (row.get("gameVersion") not in ("FR", "LG", "FRLG") or
                    completion_ready and frlg_sections_ready and frlg_schema_ready):
                return snapshot

            save_path = self.saves_dir / f"{digest}.sav"
            try:
                data = save_path.read_bytes()
            except FileNotFoundError:
                return snapshot
            except OSError as exc:
                raise SnapshotRepositoryError("A copia Native Saves nao pode ser lida.") from exc
            if hashlib.sha256(data).hexdigest() != digest:
                raise SnapshotRepositoryError("A copia Native Saves existente nao confere; preservada.")

            source = dict(kind="stored_copy", locator=row.get("filename"),
                          filename=row.get("filename", "save.bin"),
                          sizeBytes=len(data), sha256=digest)
            fresh = self.parser.parse(data, source)
            if fresh.get("gameVersion") not in ("FR", "LG", "FRLG"):
                return snapshot

            # Re-decode older FireRed snapshots after schema/format fixes,
            # retaining stored Pokemon identities and observations.
            snapshot = dict(snapshot)
            for key in ("schemaVersion", "badges", "story", "completionData",
                        "miscellany", "hallOfFame"):
                if key in fresh:
                    snapshot[key] = fresh[key]
            _json_write_atomic(self._snapshot_path(digest), snapshot)
            return snapshot

    def collection(self):
        by_id = {}
        with self.lock:
            confirmed_path = self.root / "confirmed-identities.json"
            try:
                confirmed = json.loads(confirmed_path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                confirmed = []
            except (OSError, ValueError) as exc:
                raise SnapshotRepositoryError("Historico de identidade invalido; os dados foram preservados.") from exc
            if not isinstance(confirmed, list) or any(not isinstance(item, str) for item in confirmed):
                raise SnapshotRepositoryError("Historico de identidade invalido; os dados foram preservados.")
            confirmed = set(confirmed)
            for row in self._read_index()["saves"]:
                if row.get("state") != "supported":
                    continue
                snapshot = self._read_snapshot(row["sha256"])
                for mon in snapshot["pokemon"]:
                    identity_status = ("CONFIRMED" if mon["chestLinkId"] in confirmed
                                       else mon["identityStatus"])
                    entry = by_id.get(mon["chestLinkId"])
                    observation = dict(saveHash=row["sha256"], game=snapshot["game"],
                                       observedAt=mon["observedAt"], location=mon["location"],
                                       identityStatus=identity_status)
                    if entry is None:
                        entry = dict(id=mon["chestLinkId"], species=mon["species"],
                                     speciesName=mon["species_name"], pid=mon["pid"],
                                     trainerId=mon["tid"], secretId=mon["sid"],
                                     identityStatus=identity_status, observations=[])
                        by_id[mon["chestLinkId"]] = entry
                    elif identity_status == "CONFIRMED":
                        entry["identityStatus"] = "CONFIRMED"
                    elif identity_status == "INFERRED":
                        entry["identityStatus"] = "INFERRED"
                    entry["observations"].append(observation)
        return sorted(by_id.values(), key=lambda row: (row["species"], row["id"]))

    def compare(self, before_hash, after_hash):
        with self.lock:
            return SnapshotComparator.compare(self._read_snapshot(before_hash),
                                              self._read_snapshot(after_hash))

    def journey(self, digest=None):
        with self.lock:
            index = self._read_index()
            supported = sorted((row for row in index["saves"]
                                if row.get("state") == "supported"),
                               key=lambda row: row["importedAt"])
            if digest is not None:
                selected = next((row for row in supported if row["sha256"] == digest), None)
                if selected is None:
                    raise SnapshotRepositoryError("Save Native Saves nao encontrado ou nao suportado.")
                selected_snapshot = self._read_snapshot(digest)
                selected_trainer = _trainer_key(selected_snapshot)
                supported = [row for row in supported
                             if row["importedAt"] <= selected["importedAt"] and
                             row.get("gameVersion") == selected_snapshot.get("gameVersion") and
                             row.get("game") == selected_snapshot.get("game") and
                             _trainer_key(self._read_snapshot(row["sha256"])) == selected_trainer]
            elif supported:
                latest_snapshot = self._read_snapshot(supported[-1]["sha256"])
                latest_trainer = _trainer_key(latest_snapshot)
                supported = [row for row in supported
                             if row.get("gameVersion") == latest_snapshot.get("gameVersion") and
                             row.get("game") == latest_snapshot.get("game") and
                             _trainer_key(self._read_snapshot(row["sha256"])) == latest_trainer]
            events = []
            previous = None
            story_labels = {
                "johto_champion": "Johto League champion",
                "kanto_unlocked": "Kanto unlocked",
                "game_clear": "Indigo League champion",
                "national_dex": "National Pokédex unlocked",
                "sevii_islands_1_3": "Sevii Islands 1–3 unlocked",
                "sevii_islands_4_7": "Sevii Islands 4–7 unlocked",
                "lostelle_rescued": "Lostelle rescued",
                "sevii_detour_finished": "Sevii detour completed",
                "rocket_warehouse_cleared": "Rocket Warehouse cleared",
                "ruby_recovered": "Ruby recovered",
                "sapphire_recovered": "Sapphire recovered",
                "tanoby_ruins_unlocked": "Tanoby Ruins unlocked",
            }
            for row in supported:
                snapshot = self._read_snapshot(row["sha256"])
                if previous is None:
                    for region, badges in snapshot["badges"].items():
                        for badge in badges:
                            if badge["acquired"]:
                                events.append(dict(date=row["importedAt"], label=f"{badge['name']} Badge observed",
                                                   source="DIRECT", status="observed",
                                                   saveHash=row["sha256"], location=region))
                    for key, field in snapshot.get("story", {}).items():
                        label = story_labels.get(key)
                        if label and field.get("state") == "supported" and field.get("value"):
                            events.append(dict(date=row["importedAt"], label=f"{label} observed",
                                               source="DIRECT", status="observed",
                                               saveHash=row["sha256"]))
                    events.append(dict(date=row["importedAt"], label="Initial save snapshot",
                                       source="DIRECT", status="observed", saveHash=row["sha256"]))
                else:
                    comparison = SnapshotComparator.compare(previous, snapshot)
                    for badge in comparison["badgeAdditions"]:
                        events.append(dict(date=row["importedAt"], label=f"{badge.split(':', 1)[1]} Badge first seen",
                                           source="INFERRED", status="between_snapshots",
                                           saveHash=row["sha256"]))
                    if comparison["caughtDelta"] > 0:
                        events.append(dict(date=row["importedAt"],
                                           label=f"+{comparison['caughtDelta']} Pokédex caught flags",
                                           source="INFERRED", status="between_snapshots",
                                           saveHash=row["sha256"]))
                    if comparison["playTimeDeltaSeconds"] is not None:
                        events.append(dict(date=row["importedAt"],
                                           label=f"Play time +{comparison['playTimeDeltaSeconds']} seconds",
                                           source="INFERRED", status="between_snapshots",
                                           saveHash=row["sha256"]))
                    for key, label in story_labels.items():
                        old_field = previous.get("story", {}).get(key, {})
                        new_field = snapshot.get("story", {}).get(key, {})
                        if (old_field.get("state") == new_field.get("state") == "supported" and
                                not old_field.get("value") and new_field.get("value")):
                            events.append(dict(date=row["importedAt"], label=f"{label} first seen",
                                               source="INFERRED", status="between_snapshots",
                                               saveHash=row["sha256"]))
                previous = snapshot
            manual = self._read_manual_events()
            supported_hashes = {row["sha256"] for row in supported}
            events.extend(item for item in manual if item.get("saveHash") in supported_hashes)
            events.sort(key=lambda item: (item["date"], item["source"], item["label"]))
            return dict(game=(supported[-1]["game"] if supported else None), events=events,
                        snapshots=[dict(sha256=row["sha256"], importedAt=row["importedAt"],
                                        game=row["game"]) for row in supported])

    def add_manual_event(self, request):
        if (not isinstance(request, dict) or set(request) != {"saveHash", "label"} or
                not isinstance(request["saveHash"], str) or
                not isinstance(request["label"], str) or
                not 1 <= len(request["label"].strip()) <= 120):
            raise NativeSaveError("Evento manual invalido.")
        with self.lock:
            row = next((item for item in self._read_index()["saves"]
                        if item["sha256"] == request["saveHash"]), None)
            if row is None or row.get("state") != "supported":
                raise SnapshotRepositoryError("Selecione um snapshot Native Saves valido para a Journey.")
            try:
                events = json.loads(self.manual_path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                events = []
            if not isinstance(events, list):
                raise SnapshotRepositoryError("Eventos Journey invalidos; os dados foram preservados.")
            event = dict(date=datetime_now(), label=request["label"].strip(), source="MANUAL",
                         status="user_recorded", saveHash=request["saveHash"])
            events.append(event)
            _json_write_atomic(self.manual_path, events)
            return event

    def completion(self, digest):
        with self.lock:
            snapshot = self._read_snapshot(digest)
            save_path = self.saves_dir / f"{digest}.sav"
            try:
                data = save_path.read_bytes()
            except FileNotFoundError:
                data = None
            except OSError as exc:
                raise SnapshotRepositoryError("A copia Native Saves nao pode ser lida.") from exc
            if data is not None:
                if hashlib.sha256(data).hexdigest() != digest:
                    raise SnapshotRepositoryError("A copia Native Saves existente nao confere; preservada.")
                row = next((item for item in self._read_index()["saves"]
                            if item["sha256"] == digest), None)
                if row is None or row.get("state") != "supported":
                    raise SnapshotRepositoryError("Save Native Saves nao encontrado.")
                source = dict(kind="stored_copy", locator=row.get("filename"),
                              filename=row.get("filename", "save.bin"),
                              sizeBytes=len(data), sha256=digest)
                fresh = self.parser.parse(data, source)
                if fresh.get("gameVersion") in ("FR", "LG", "FRLG"):
                    snapshot = dict(snapshot)
                    snapshot["completionData"] = fresh.get("completionData", {})
            return CompletionTracker.evaluate(snapshot)

    def confirm_transfer(self, identity_id):
        """Mark a previously observed identity confirmed after a direct transfer."""
        if not isinstance(identity_id, str) or len(identity_id) != 36:
            raise NativeSaveError("Identificador interno de Pokemon invalido.")
        with self.lock:
            if not any(mon["chestLinkId"] == identity_id for row in self._read_index()["saves"]
                       if row.get("state") == "supported"
                       for mon in self._read_snapshot(row["sha256"])["pokemon"]):
                return False
            path = self.root / "confirmed-identities.json"
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                data = []
            if not isinstance(data, list) or any(not isinstance(item, str) for item in data):
                raise SnapshotRepositoryError("Historico de identidade invalido; os dados foram preservados.")
            if identity_id not in data:
                data.append(identity_id)
                _json_write_atomic(path, data)
            return True


def _safe_filename(name):
    name = str(name).replace("\\", "/").split("/")[-1]
    name = "".join(char for char in name if char >= " " and char != "\x7f")[:128]
    return name or "save.bin"


def datetime_now():
    return datetime.now(timezone.utc).isoformat()


def _write_bytes_new(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    try:
        descriptor = os.open(path, flags, 0o600)
    except FileExistsError:
        if hashlib.sha256(path.read_bytes()).hexdigest() != hashlib.sha256(data).hexdigest():
            raise SnapshotRepositoryError("A copia Native Saves existente nao confere; preservada.")
        return
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    except BaseException:
        try:
            path.unlink()
        except OSError:
            pass
        raise
