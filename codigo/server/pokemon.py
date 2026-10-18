"""Read-only PKX summaries, matching source/pokemon.cpp.

Derived from PKSM-Core (C) 2016-2022 Bernardo Giordano, Admiral Fish, piepie62.
GPL-3.0-or-later, upstream section 7(b)/(c) attribution/origin notices apply.
Raw records are never changed by the preview decoder.
"""
import json
from bisect import bisect_right
from pathlib import Path
import struct

ASSETS = Path(__file__).resolve().parent / "web" / "assets"
CATALOG = json.loads((ASSETS / "catalog.json").read_text())
FORMS = json.loads((ASSETS / "sprites.json").read_text()) if (ASSETS / "sprites.json").exists() else {}
GROWTH = json.loads((ASSETS / "growth-rates.json").read_text(encoding="utf-8"))
GENERATIONS = ["IV", "V", "VI", "VII", "LGPE", "VIII", "III", "I", "II"]
NATIONAL_DEX_SIZE_BY_GENERATION = {
    1: 151, 2: 251, 3: 386, 4: 493, 5: 649,
    6: 721, 7: 809, 8: 905, 9: 1025,
}


def national_species_ids():
    """Species that can occupy a HOME card; forms/eggs are not extra species."""
    names = CATALOG["names"]
    return sorted({int(key) for key, sprite in FORMS.items()
                   if key.isdecimal() and 0 < int(key) < len(names)
                   and names[int(key)] and type(sprite) is int and sprite > 0})


def national_species_ids_for_generation(generation):
    """Numbered species in a generation's National Dex scope.

    Generation I uses the same 151-species scope as Kanto for comparison.
    """
    size = NATIONAL_DEX_SIZE_BY_GENERATION.get(generation)
    return list(range(1, size + 1)) if size else []


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


def experience_level(species, experience):
    """Return the level from the species growth curve and stored experience."""
    growth_rates = GROWTH["growthRateBySpecies"]
    if not 0 < species < len(growth_rates):
        return None
    curve = GROWTH["experienceByGrowthRate"].get(str(growth_rates[species]))
    if not curve:
        return None
    return max(1, min(100, bisect_right(curve[1:], experience)))


def preview(entry):
    if len(entry) != 336:
        raise ValueError("Registro de tamanho invalido.")
    gen = u32(entry, 0)
    out = dict(occupied=gen != 0xffffffff, valid=False, egg=False, shiny=False,
               species=0, form=0, generation=gen, sprite=0, level=None,
               name="Registro desconhecido")
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
            # Virtual Console Gen I records retain PK1's stored box level.
            level = p[6]
        else:
            species = internal
            limit = 251
            egg = p[1] == 0xfd
            # PK2 stores EXP in a 24-bit big-endian field after its list header.
            experience = int.from_bytes(p[11:14], "big")
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
        level = experience_level(species, u32(p, 40))
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
            level = experience_level(species, u32(p, 16))
        elif gen == 5:
            form, egg, pid = u16(p, 36), bool(u32(p, 140) >> 30 & 1), u32(p, 28)
            level = experience_level(species, u32(p, 16))
        else:
            form, egg, pid, limit = p[29] >> 3, bool(u32(p, 116) >> 30 & 1), u32(p, 24), 721 if gen == 2 else 809
            level = experience_level(species, u32(p, 16))
    if gen == 8:
        level = experience_level(species, experience)
    if egg:
        level = None
    if not 0 < species <= limit:
        return out
    out.update(valid=True, species=species, form=form, egg=egg,
               level=level if type(level) is int and 1 <= level <= 100 else None,
               shiny=out["shiny"] if gen >= 7 else (tid ^ sid ^ (pid & 65535) ^ (pid >> 16)) < (8 if gen in (0, 1, 6) else 16),
               sprite=sprite_for(species, form, gen, egg), name=CATALOG["names"][species])
    return out
