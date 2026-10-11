"""Read-only PKX summaries, matching source/pokemon.cpp.

Derived from PKSM-Core (C) 2016-2022 Bernardo Giordano, Admiral Fish, piepie62.
GPL-3.0-or-later, upstream section 7(b)/(c) attribution/origin notices apply.
Raw records are never changed by the preview decoder.
"""
import json
from pathlib import Path
import struct

ASSETS = Path(__file__).resolve().parent / "web" / "assets"
CATALOG = json.loads((ASSETS / "catalog.json").read_text())
FORMS = json.loads((ASSETS / "sprites.json").read_text()) if (ASSETS / "sprites.json").exists() else {}
GENERATIONS = ["IV", "V", "VI", "VII", "LGPE", "VIII", "III", "I", "II"]


def u16(p, offset):
    return struct.unpack_from("<H", p, offset)[0]


def u32(p, offset):
    return struct.unpack_from("<I", p, offset)[0]


def checksum(p, start, length):
    return sum(struct.unpack_from("<" + "H" * (length // 2), p, start)) & 65535


def shuffle(p, start, block, index):
    raw = p[start:start + block * 4]
    order = CATALOG["blockPositions"][(index % 24) * 4:(index % 24) * 4 + 4]
    for i, source in enumerate(order):
        p[start + i * block:start + (i + 1) * block] = raw[source * block:(source + 1) * block]


def sprite_for(species, form, generation, egg):
    if egg:
        return FORMS.get("egg", 0)
    # Sprite atlas uses numeric keys from the upstream icon catalogue. Form
    # indices are generation-specific; missing artwork retains the base icon.
    return FORMS.get(f"{generation}:{species}:{form}", FORMS.get(str(species), 0))


def preview(entry):
    if len(entry) != 336:
        raise ValueError("Registro de tamanho invalido.")
    gen = u32(entry, 0)
    out = dict(occupied=gen != 0xffffffff, valid=False, egg=False, shiny=False,
               species=0, form=0, generation=gen, sprite=0, name="Registro desconhecido")
    if not out["occupied"]:
        out["name"] = "Vazio"
        return out
    if gen > 8:
        return out
    p = bytearray(entry[4:332])
    pid = tid = sid = 0
    form = 0
    egg = False
    limit = 898
    if gen in (7, 8):
        internal = p[3]
        if gen == 7:
            if internal >= len(CATALOG["g1ToSpecies"]):
                return out
            species = CATALOG["g1ToSpecies"][internal]
            limit = 151
        else:
            species = internal
            limit = 251
            egg = p[1] == 0xfd
            if species == 201:
                a, d = p[24] >> 4, p[24] & 15
                speed, sp = p[25] >> 4, p[25] & 15
                form = (((a & 6) << 5) | ((d & 6) << 3) | ((speed & 6) << 1) | ((sp & 6) >> 1)) // 10
        if not egg and p[1] != p[3]:
            return out
        dv = 30 if gen == 7 else 24
        out["shiny"] = (p[dv] & 15) == 10 and p[dv + 1] >> 4 == 10 and (p[dv + 1] & 15) == 10 and bool((p[dv] >> 4) & 2)
    elif gen == 6:
        if checksum(p, 32, 48) != u16(p, 28):
            key = u32(p, 0) ^ u32(p, 4)
            for i in range(32, 80):
                p[i] ^= (key >> ((i & 3) * 8)) & 255
            shuffle(p, 32, 12, u32(p, 0) % 24)
            if checksum(p, 32, 48) != u16(p, 28):
                return out
        internal = u16(p, 32)
        if internal >= len(CATALOG["g3ToSpecies"]):
            return out
        species = CATALOG["g3ToSpecies"][internal]
        limit = 386
        egg = bool(u32(p, 72) >> 30 & 1)
        pid, tid, sid = u32(p, 0), u16(p, 4), u16(p, 6)
        if species == 201:
            form = (((pid & 0x3000000) >> 18) | ((pid & 0x30000) >> 12) |
                    ((pid & 0x300) >> 6) | (pid & 3)) % 28
    else:
        length = 128 if gen <= 1 else 320 if gen == 5 else 224
        if checksum(p, 8, length) != u16(p, 6):
            seed = u16(p, 6) if gen <= 1 else u32(p, 0)
            for i in range(8, 8 + length, 2):
                seed = (seed * 0x41c64e6d + 0x6073) & 0xffffffff
                p[i] ^= seed >> 16 & 255
                p[i + 1] ^= seed >> 24
            shuffle(p, 8, length // 4, u32(p, 0) >> 13 & 31)
            if checksum(p, 8, length) != u16(p, 6):
                return out
        species = u16(p, 8)
        tid, sid = u16(p, 12), u16(p, 14)
        if gen <= 1:
            form, egg, pid, limit = p[64] >> 3, bool(u32(p, 56) >> 30 & 1), u32(p, 0), 493 if gen == 0 else 649
        elif gen == 5:
            form, egg, pid = u16(p, 36), bool(u32(p, 140) >> 30 & 1), u32(p, 28)
        else:
            form, egg, pid, limit = p[29] >> 3, bool(u32(p, 116) >> 30 & 1), u32(p, 24), 721 if gen == 2 else 809
    if not 0 < species <= limit:
        return out
    out.update(valid=True, species=species, form=form, egg=egg,
               shiny=out["shiny"] if gen >= 7 else (tid ^ sid ^ (pid & 65535) ^ (pid >> 16)) < (8 if gen in (0, 1, 6) else 16),
               sprite=sprite_for(species, form, gen, egg), name=CATALOG["names"][species])
    return out
