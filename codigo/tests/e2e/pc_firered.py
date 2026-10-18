"""Exercise PC collection, selection, delivery and progress with private PK3."""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from server import pokemon
from tests.e2e.artifacts import RunArtifacts
from tests.e2e.config import Environment
from tests.e2e.firered import create_firered_bank
from tests.e2e.private_saves import PrivateSaveGuard
from tests.e2e.probe_runner import api, host_upload
from tests.e2e.run import RunContext
from tests.e2e.scenarios.common import start_pc_server, wait_server_ready, stop_server


def check(value, message):
    if not value: raise AssertionError(message)


def run():
    path = os.environ['CHESTLINK_FIRERED_SAVE']
    guard = PrivateSaveGuard(path)
    artifacts = RunArtifacts(ROOT / 'build/e2e')
    ctx = RunContext(artifacts, Environment.detect(), 90, build=False)
    ctx.scenario_name = 'pc_firered'
    print('Private run: ' + str(artifacts.path), flush=True)
    try:
        fixture = create_firered_bank(path, artifacts.path / 'private/fixture')
        start_pc_server(ctx)
        wait_server_ready(ctx)
        item_id = host_upload(ctx, fixture)
        original = fixture['bank'].read_bytes()
        counts = {}; home_counts = {}; occupied = valid = 0
        masks = [0] * fixture['boxes']
        selected = 0
        for box_number in range(fixture['boxes']):
            box = api(ctx, f'/api/box?id={item_id}&box={box_number}')
            check(len(box['pokemon']) == 30, 'A PC box lost its slot positions.')
            for slot, preview in enumerate(box['pokemon']):
                offset = 16 + (box_number * 30 + slot) * 336
                expected = pokemon.preview(original[offset:offset + 336])
                check(preview == expected, 'PC box preview differs from the raw private PK3 record.')
                if preview['occupied']:
                    occupied += 1; valid += preview['valid']
                    if preview['valid']:
                        species_id = str(preview['species'])
                        home_counts[species_id] = home_counts.get(species_id, 0) + 1
                    if 1 <= preview['species'] <= 151:
                        species = str(preview['species'])
                        counts[species] = counts.get(species, 0) + 1
                    if selected < 3:
                        masks[box_number] |= 1 << slot
                        selected += 1
        check(occupied == valid == fixture['occupied'], 'PC did not decode all private PK3 records.')
        dex = api(ctx, '/api/pokedex')
        check(dex['serverCounts'] == counts, 'PC server collection counts differ from its boxes.')
        check(set(dex['serverCaptured']) == {int(k) for k in counts}, 'Captured registry is incomplete.')
        catalogue = api(ctx, '/api/pokedex/catalog')
        check(dex['homeServerCounts'] == home_counts and dex['homeSpeciesTotal'] == len(catalogue['species']),
              'HOME did not count the national collection independently from the Gen I catalogue.')
        check(set(dex['homeServerCaptured']) == {int(k) for k in home_counts},
              'HOME captured registry omitted records from other generations.')
        print('PC boxes: 86 valid PK3; collection counts and captured registry: PASS', flush=True)
        print(f"HOME: {len(home_counts)} national species, {sum(home_counts.values())} records: PASS", flush=True)

        included = [i for i, mask in enumerate(masks) if mask]
        expected_bank = bytearray(b'PKSMBANK' + struct.pack('<II', 3, len(included)))
        for b in included:
            for s in range(30):
                offset = 16 + (b * 30 + s) * 336
                expected_bank.extend(original[offset:offset + 336] if masks[b] & (1 << s)
                                     else bytes([0xFF]) * 336)
        for target in (1, 2):
            queued = api(ctx, '/api/requeue', dict(id=item_id, target=target, masks=masks))
            stored = ctx.server['data_root'] / 'items' / queued['id']
            check((stored / 'bank.bnk').read_bytes() == expected_bank,
                  'Individual selection changed records or slot positions.')
            destination = artifacts.path / f'private/received-{target}'
            command = [str(ROOT / 'build/chest-link-cli'), 'mail-fetch', str(destination),
                       '127.0.0.1', '314159', str(target), queued['id'], str(ctx.server['tcp_port'])]
            first = subprocess.run(command, capture_output=True, text=True, timeout=30)
            second = subprocess.run(command, capture_output=True, text=True, timeout=30)
            check(first.returncode == second.returncode == 0 and 'IMPORTED' in first.stdout and
                  'REUSED' in second.stdout, 'Import/retry receipt did not preserve idempotency.')
            check(json.loads((stored / 'meta.json').read_text())['delivered'], 'Delivery ACK was not stored.')
            received = list((destination / 'banks').glob('*.bnk'))
            check(len(received) == 1 and received[0].read_bytes() == expected_bank,
                  'The delivered selection does not match the private source.')
            reopened = api(ctx, '/api/requeue', dict(id=item_id, target=target, masks=masks))
            check(reopened['id'] == queued['id'] and
                  not json.loads((stored / 'meta.json').read_text())['delivered'],
                  'Explicit resend did not reopen the preserved copy.')
        print('Individual selection to DS/3DS, delivery, duplicate retry and resend: PASS', flush=True)

        species = next(iter(map(int, counts)))
        updated = api(ctx, '/api/pokedex', dict(mode='unified', game='red', species=species, captured=True))
        check(species in updated['unified'] and all(species in updated['individual'][game]
              for game in ('red', 'blue', 'yellow')), 'Unified progress was not propagated.')
        updated = api(ctx, '/api/pokedex', dict(mode='individual', game='blue', species=species, captured=False))
        check(species in updated['individual']['red'] and species not in updated['individual']['blue'],
              'Individual progress changed the other games.')
        before_clear = dict(api(ctx, '/api/pokedex')['serverCounts'])
        cleared = api(ctx, '/api/clear-pending', {})
        check(cleared['cleared'] > 0, 'Pending queue did not clear.')
        check(api(ctx, '/api/pokedex')['serverCounts'] == before_clear,
              'Clearing pending deliveries deleted collection records.')
        check((ctx.server['data_root'] / 'items' / item_id / 'bank.bnk').read_bytes() == original,
              'PC original backup changed during the operations.')
        port = ctx.server['tcp_port']
        token = (ctx.server['data_root'] / 'interface-token.json').read_bytes()
        check(stop_server(ctx), 'Server port did not close.')
        start_pc_server(ctx, tcp_port=port, reuse=True)
        wait_server_ready(ctx)
        persisted = api(ctx, '/api/pokedex')
        check(persisted['serverCounts'] == before_clear and persisted['individual'] == updated['individual'],
              'Progress did not survive the server restart.')
        check((ctx.server['data_root'] / 'interface-token.json').read_bytes() == token,
              'The interface link/token changed after restart.')
        check(fixture['bank'].read_bytes() == original, 'The source FireRed bank was modified.')
        print('Progress persistence, pending cleanup, PC backups and server restart: PASS', flush=True)
        artifacts.record('pc_firered', 'PASS', 'HOST', metrics={
            'private_fixture': 'FireRed', 'pokemon': occupied,
            'individual_selection': True, 'both_targets': True, 'retry': True,
            'resend': True, 'collection_registry': True, 'progress_persistence': True,
            'pending_cleanup': True, 'backups_preserved': True})
    except Exception as exc:
        print(type(exc).__name__ + ': ' + str(exc), flush=True)
        artifacts.record('pc_firered', 'FAIL', 'HOST', reason=str(exc))
    finally:
        ctx.processes.stop_all(); guard.verify_unchanged()
        artifacts.write_summary('pc_firered', {'private_fixture': 'FireRed'})
    return 1 if any(row['status'] == 'FAIL' for row in artifacts.results) else 0


if __name__ == '__main__': sys.exit(run())
