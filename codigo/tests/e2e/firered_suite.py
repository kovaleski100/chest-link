"""Run the private FireRed regression matrix without using user storage."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.e2e.config import Environment
from tests.e2e.build_console_probe import build


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-build', action='store_true')
    parser.add_argument('--normal-ui', action='store_true',
                        help='Also navigate normal release binaries on X11.')
    args = parser.parse_args()
    if not os.environ.get('CHESTLINK_FIRERED_SAVE'):
        print('SKIP FireRed: CHESTLINK_FIRERED_SAVE is not configured.')
        return 0
    env = Environment.detect()
    commands = [('pc_firered', ['pc_firered.py'])]
    if env.melon_ds and env.azahar:
        if not args.no_build: build()
        for console in ('ds', '3ds'):
            ip = '10.64.0.1' if console == 'ds' else '127.0.0.1'
            for mode in ('preview', 'upload', 'fetch', 'update'):
                commands.append((console + '_' + mode,
                                 ['probe_runner.py', console, mode, '--ip', ip]))
        commands.extend([
            ('3ds_direct_receive', ['probe_runner.py', '3ds', 'direct_receive', '--ip', '127.0.0.1']),
            ('ds_to_3ds', ['paired_transfers.py', 'ds_to_3ds']),
        ])
        if env.melon_ds.endswith('melonds_forward.py'):
            commands.extend([
                ('ds_direct_receive', ['probe_runner.py', 'ds', 'direct_receive']),
                ('3ds_to_ds', ['paired_transfers.py', '3ds_to_ds']),
            ])
        else:
            print('SKIP inbound DS: use the documented melonDS NAT forwarding wrapper.')
        if args.normal_ui:
            if env.display_session == 'x11':
                for console in ('ds', '3ds'):
                    commands.append((console + '_normal_ui',
                                     ['normal_ui_transfer.py', console, '--auto-ui']))
            else:
                print('SKIP normal UI navigation: X11 is required.')
    else:
        print('SKIP emulator matrix: configure both CHESTLINK_MELONDS and CHESTLINK_AZAHAR.')
    failed = []
    for name, command in commands:
        print('RUN ' + name, flush=True)
        result = subprocess.run([sys.executable, str(ROOT / 'tests/e2e' / command[0]), *command[1:]],
                                cwd=ROOT, check=False)
        if result.returncode: failed.append(name)
    print('FAIL: ' + ', '.join(failed) if failed else 'PASS: all executed FireRed scenarios.', flush=True)
    return 1 if failed else 0


if __name__ == '__main__': sys.exit(main())
