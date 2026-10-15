"""Transfer the same private FireRed records directly between both emulators."""
import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.e2e.artifacts import RunArtifacts
from tests.e2e.config import Environment
from tests.e2e.firered import create_firered_bank
from tests.e2e.private_saves import PrivateSaveGuard
from tests.e2e.probe_runner import prepare, await_result
from tests.e2e.run import RunContext


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('direction', choices=('ds_to_3ds', '3ds_to_ds'))
    args = parser.parse_args()
    path = os.environ['CHESTLINK_FIRERED_SAVE']
    guard = PrivateSaveGuard(path)
    artifacts = RunArtifacts(ROOT / 'build/e2e')
    ctx = RunContext(artifacts, Environment.detect(), 90, build=False)
    print('Private run: ' + str(artifacts.path), flush=True)
    sender_result = {}
    try:
        fixture = create_firered_bank(path, artifacts.path / 'private/fixture')
        source, destination = ('ds', '3ds') if args.direction == 'ds_to_3ds' else ('3ds', 'ds')
        config = dict(pin=314159, port=40991, ip='127.0.0.1')
        receiver = prepare(ctx, destination, 'direct_receive', fixture, config)
        def on_stage(stage, _result):
            if stage == 'listening':
                peer = '10.64.0.1' if source == 'ds' else '127.0.0.1'
                sender = prepare(ctx, source, 'direct_send', fixture, dict(config, ip=peer))
                sender_result.update(await_result(ctx, sender))
                if sender_result.get('status') != 'PASS':
                    raise RuntimeError('Sending emulator failed: ' + sender_result.get('error', 'unknown'))
        result = await_result(ctx, receiver, on_stage=on_stage)
        if result.get('status') != 'PASS': raise RuntimeError(result.get('error', 'Receiving emulator failed.'))
        for name, row in ((source, sender_result), (destination, result)):
            if row.get('bank_sha256') != fixture['bank_sha256'] or row.get('valid_pk3') != fixture['occupied']:
                raise AssertionError(name + ' bank bytes/counts differ from the private FireRed source.')
        artifacts.write_private_json('sender.json', sender_result)
        artifacts.write_private_json('receiver.json', result)
        artifacts.record(args.direction + '_firered', 'PASS', 'EMULATOR', metrics={
            'source': source, 'destination': destination, 'private_fixture': 'FireRed',
            'pokemon': fixture['occupied'], 'receiver_bank_sha256_verified': True,
            'sender_bank_preserved': True, 'direct_delivery_ack': True,
            'ds_nat_forwarding': destination == 'ds'})
        print('PASS: both emulator banks match the private source; destination ACK confirmed.', flush=True)
    except Exception as exc:
        artifacts.record(args.direction + '_firered', 'FAIL', 'EMULATOR', reason=str(exc))
        print(type(exc).__name__ + ': ' + str(exc), flush=True)
    finally:
        ctx.processes.stop_all(); guard.verify_unchanged()
        artifacts.write_summary(args.direction, {'private_fixture': 'FireRed'})
    return 1 if any(row['status'] == 'FAIL' for row in artifacts.results) else 0


if __name__ == '__main__': sys.exit(main())
