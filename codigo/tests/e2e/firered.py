"""Read-only private FireRed fixture preparation for bank/transfer tests.

Layout reference: pret/pokefirered include/save.h, global.h and
pokemon_storage_system.h. This adapter is test infrastructure, not a user save
importer. Raw encrypted PK3 records are copied without changing their contents.
"""
import hashlib
import json
import os
from pathlib import Path
import struct

from tests.e2e.private_saves import PrivateSaveGuard, PrivateSaveError

SECTION_LENGTHS = (0xF24, 0xF80, 0xF80, 0xF80, 0xEE8,
                   *([0xF80] * 8), 0x7D0)


def _checksum(data):
    total = sum(struct.unpack('<' + 'I' * (len(data) // 4), data)) & 0xFFFFFFFF
    return ((total >> 16) + (total & 0xFFFF)) & 0xFFFF


def _slot(data, slot):
    sections = {}
    counters = set()
    for sector in range(14):
        start = (slot * 14 + sector) * 4096
        block = data[start:start + 4096]
        sid, checksum, magic, counter = struct.unpack_from('<HHII', block, 0xFF4)
        if sid >= 14 or sid in sections or magic != 0x08012025:
            return None
        payload = block[:SECTION_LENGTHS[sid]]
        if _checksum(payload) != checksum:
            return None
        sections[sid] = payload
        counters.add(counter)
    if len(counters) != 1:
        return None
    return counters.pop(), sections


def _valid_pk3(raw):
    if not raw[19] & 2:
        return False
    key = struct.unpack_from('<I', raw)[0] ^ struct.unpack_from('<I', raw, 4)[0]
    words = struct.unpack_from('<12I', raw, 32)
    plain = struct.pack('<12I', *(word ^ key for word in words))
    checksum = sum(struct.unpack('<24H', plain)) & 0xFFFF
    if checksum != struct.unpack_from('<H', raw, 28)[0]:
        raise PrivateSaveError('Um registro PK3 ocupado tem checksum inválido.')
    return True


def create_firered_bank(save_path, destination):
    """Create a private PKSM v3 bank: 14 boxes plus a copy of the party."""
    guard = PrivateSaveGuard(save_path)
    data = guard.path.read_bytes()
    if len(data) != 0x20000:
        raise PrivateSaveError('O teste FireRed exige um save bruto de 128 KiB.')
    slots = [result for i in (0, 1) if (result := _slot(data, i)) is not None]
    if not slots:
        raise PrivateSaveError('Nenhum slot FRLG completo com checksums válidos.')
    active = slots[0]
    for candidate in slots[1:]:
        difference = (candidate[0] - active[0]) & 0xFFFFFFFF
        if 0 < difference < 0x80000000:
            active = candidate
    _counter, sections = active
    storage = b''.join(sections[i] for i in range(5, 14))
    records = [storage[4 + i * 80:4 + (i + 1) * 80] for i in range(420)]
    party_count = sections[1][0x34]
    if party_count > 6:
        raise PrivateSaveError('A quantidade da party FireRed excede seis.')
    party = [sections[1][0x38 + i * 100:0x38 + i * 100 + 80]
             for i in range(party_count)]
    records.extend(party + [bytes(80)] * (30 - party_count))
    bank = bytearray(b'PKSMBANK' + struct.pack('<II', 3, 15))
    boxed = party_valid = 0
    for i, raw in enumerate(records):
        if _valid_pk3(raw):
            entry = bytearray(336)
            struct.pack_into('<I', entry, 0, 6)  # PKSM generation enum: PK3
            entry[4:84] = raw
            boxed += i < 420
            party_valid += i >= 420
        else:
            entry = bytes([0xFF]) * 336
        bank.extend(entry)
    if party_valid != party_count or not boxed + party_valid:
        raise PrivateSaveError('A party está incompleta ou o save não contém Pokémon.')
    root = Path(destination)
    banks = root / 'banks'
    banks.mkdir(parents=True, mode=0o700)
    names = [f'FireRed Box {i + 1:02d}' for i in range(14)] + ['FireRed Party Copy']
    (banks / 'firered.bnk').write_bytes(bank)
    (banks / 'firered.json').write_text(json.dumps(names) + '\n')
    (root / 'banks.json').write_text('{"firered":15}\n')
    for path in (root / 'banks.json', banks / 'firered.bnk', banks / 'firered.json'):
        os.chmod(path, 0o600)
    guard.verify_unchanged()
    return dict(store=root, bank=banks / 'firered.bnk', names=banks / 'firered.json',
                boxes=15, occupied=boxed + party_valid, boxed=boxed,
                party=party_valid, bank_sha256=hashlib.sha256(bank).hexdigest(),
                source_sha256=guard.sha256, source_fixture='private_firered',
                original_preserved=True)
