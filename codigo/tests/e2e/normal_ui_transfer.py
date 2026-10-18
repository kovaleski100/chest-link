"""Normal application UI smoke: operator selects/sends, server verifies bytes."""
import argparse
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.e2e.artifacts import RunArtifacts
from tests.e2e.config import Environment
from tests.e2e.firered import create_firered_bank
from tests.e2e.private_saves import PrivateSaveGuard
from tests.e2e.probe_runner import prepare
from tests.e2e.run import RunContext
from tests.e2e.scenarios.common import start_pc_server, wait_server_ready, wait_for_new_item


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('console', choices=('ds', '3ds'))
    parser.add_argument('--auto-ui', action='store_true')
    args = parser.parse_args()
    path = os.environ['CHESTLINK_FIRERED_SAVE']
    guard = PrivateSaveGuard(path)
    artifacts = RunArtifacts(ROOT / 'build/e2e')
    ctx = RunContext(artifacts, Environment.detect(), 180, build=False)
    ctx.scenario_name = args.console + '_normal_ui_firered'
    print('Private run: ' + str(artifacts.path), flush=True)
    try:
        fixture = create_firered_bank(path, artifacts.path / 'private/fixture')
        start_pc_server(ctx, bind='0.0.0.0', tcp_port=40992)
        wait_server_ready(ctx)
        peer = '10.64.0.1' if args.console == 'ds' else '127.0.0.1'
        probe = prepare(ctx, args.console, 'upload', fixture,
                        dict(ip=peer, pin=314159, port=40992), normal=True)
        print('Normal app: Consultar bancos -> firered -> X: todas -> enviar PC -> confirm IP/PIN.', flush=True)
        if args.auto_ui:
            from tests.e2e.ui_driver import NormalUIDriver
            NormalUIDriver(args.console, artifacts.path / 'private').send_all_to_pc()
        row = wait_for_new_item(ctx, set(), 300, emulator=probe['process'])
        if row is None: raise TimeoutError('Normal UI did not finish the transfer.')
        bank = ctx.server['data_root'] / 'items' / row['id'] / 'bank.bnk'
        if bank.read_bytes() != fixture['bank'].read_bytes() or row['offer']['occupied'] != fixture['occupied']:
            raise AssertionError('Normal UI transfer changed the private FireRed records.')
        artifacts.record(ctx.scenario_name, 'PASS', 'EMULATOR_NORMAL_UI', metrics={
            'private_fixture': 'FireRed', 'pokemon': fixture['occupied'], 'boxes': fixture['boxes'],
            'server_ack': True, 'exact_bytes_verified': True, 'normal_release_binary': True,
            'operator_navigation': not args.auto_ui,
            'automatic_navigation': args.auto_ui})
        print('PASS: normal app sent all 86 PK3; server bytes and counts match.', flush=True)
    except Exception as exc:
        artifacts.record(ctx.scenario_name, 'FAIL', 'EMULATOR_NORMAL_UI', reason=str(exc))
        print(type(exc).__name__ + ': ' + str(exc), flush=True)
    finally:
        ctx.processes.stop_all(); guard.verify_unchanged()
        artifacts.write_summary(ctx.scenario_name, {'private_fixture': 'FireRed'})
    return 1 if any(row['status'] == 'FAIL' for row in artifacts.results) else 0


if __name__ == '__main__': sys.exit(main())
