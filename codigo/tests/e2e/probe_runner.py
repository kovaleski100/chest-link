"""Deterministic, private FireRed tests through actual emulated console cores."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
from urllib.request import Request, urlopen
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tests.e2e.artifacts import RunArtifacts
from tests.e2e.config import Environment
from tests.e2e.firered import create_firered_bank
from tests.e2e.private_saves import PrivateSaveGuard
from tests.e2e.run import RunContext
from tests.e2e.scenarios.common import start_pc_server, wait_server_ready, read_server_state, stop_server, free_port
from tests.e2e.scenarios.emulator_boot import _isolated_env

PROBE_SOURCE = ROOT / 'build/e2e/console-probe/source'
SAVED_PROFILE = ROOT / 'build/e2e/profiles'


def api(ctx, path, body=None):
    origin = f"http://127.0.0.1:{ctx.server['web_port']}"
    token = json.loads((ctx.server['data_root'] / 'interface-token.json').read_text())['token']
    headers = {'Authorization': 'Bearer ' + token, 'Origin': origin}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers['Content-Type'] = 'application/json'
    with urlopen(Request(origin + path, data=data, headers=headers), timeout=120) as response:
        return json.load(response)


def host_upload(ctx, fixture):
    command = [str(ROOT / 'build/chest-link-cli'), 'mail-send', str(fixture['store']),
               'firered', ','.join(str(i + 1) for i in range(fixture['boxes'])),
               '127.0.0.1', '314159', '0', str(ctx.server['tcp_port'])]
    response = subprocess.run(command, capture_output=True, text=True, timeout=30)
    if response.returncode:
        raise RuntimeError('Private FireRed host upload failed: ' + response.stderr)
    match = re.search(r'STORED ([0-9a-f]{32})', response.stdout)
    if not match: raise AssertionError('Host upload did not receive a server ACK.')
    return match[1]


def prepare(ctx, console, mode, fixture, config, *, normal=False):
    area = ctx.artifacts.path / console
    area.mkdir(exist_ok=True, mode=0o700)
    profile = area / 'profile'
    env = _isolated_env(profile)
    env['APPIMAGE_EXTRACT_AND_RUN'] = '1'
    if console == 'ds' and ctx.environment.melon_ds.endswith('melonds_forward.py'):
        env['CHESTLINK_E2E_CONTAINER_ID'] = str(area / 'container-id')
    if console == 'ds':
        if mode == 'direct_receive': env['CHESTLINK_DS_FORWARD'] = '40991'
        storage = area / 'dldi'
        app = storage / 'chest-link-e2e'
        image = area / 'dldi.img'
        cfg = Path(env['XDG_CONFIG_HOME']) / 'melonDS/melonDS.toml'
        cfg.parent.mkdir(parents=True, exist_ok=True)
        cfg.write_text('[Emu]\nDirectBoot = true\nExternalBIOSEnable = false\n'
                       '[LAN]\nDirectMode = false\n'
                       '[DLDI]\nEnable = true\nReadOnly = false\nFolderSync = true\n'
                       f'ImagePath = {json.dumps(str(image))}\n'
                       f'FolderPath = {json.dumps(str(storage))}\n'
                       '[JIT]\nEnable = false\n'
                       '[Instance0]\n\n[Instance0.Keyboard]\nA = 88\nB = 90\nX = 83\nY = 65\n'
                       'Start = 16777220\nDown = 16777237\nUp = 16777235\n')
        wifi = storage / '_nds/chest-link'
        wifi.mkdir(parents=True)
        (wifi / 'wifi-ssid.txt').write_text('melonAP')
        binary = PROBE_SOURCE / 'platform/nds/ChestLink_DS.nds'
        program = ctx.environment.melon_ds
    else:
        storage = area / 'sdmc'
        app = storage / 'chest-link-e2e'
        data = Path(env['XDG_DATA_HOME']) / 'azahar-emu'
        for name in ('sysdata', 'nand'):
            src = SAVED_PROFILE / 'azahar/data/azahar-emu' / name
            if src.is_dir():
                shutil.copytree(src, data / name, dirs_exist_ok=True)
        cfg = Path(env['XDG_CONFIG_HOME']) / 'azahar-emu/qt-config.ini'
        cfg.parent.mkdir(parents=True, exist_ok=True)
        saved = (SAVED_PROFILE / 'azahar/config/azahar-emu/qt-config.ini').read_text()
        saved = re.sub(r'(?m)^sdmc_directory=.*$', 'sdmc_directory=' + str(storage) + '/', saved)
        saved = re.sub(r'(?m)^sdmc_directory\\default=.*$', lambda _m: 'sdmc_directory\\default=false', saved)
        saved = re.sub(r'(?m)^use_custom_storage=.*$', 'use_custom_storage=true', saved)
        saved = re.sub(r'(?m)^use_custom_storage\\default=.*$', lambda _m: 'use_custom_storage\\default=false', saved)
        cfg.write_text(saved)
        binary = PROBE_SOURCE / 'platform/3ds/ChestLink_3DS.3dsx'
        program = ctx.environment.azahar
        image = None
    app.mkdir(parents=True, mode=0o700)
    shutil.copytree(fixture['store'], app / 'store')
    if mode == 'update' and console == '3ds':
        install = app / 'install'; install.mkdir()
        # An optional predecessor tests backup preservation with different bytes.
        # Otherwise seed the current executable and simulate an older version;
        # the normal updater still downloads, verifies and installs the build.
        previous = os.environ.get('CHESTLINK_3DS_PREVIOUS_APP')
        predecessor = Path(previous).expanduser() if previous else ROOT / 'platform/3ds/ChestLink_3DS.3dsx'
        if predecessor.suffix == '.zip':
            with ZipFile(predecessor) as archive:
                names = [name for name in archive.namelist() if name.endswith('ChestLink_3DS.3dsx')]
                if len(names) != 1: raise RuntimeError('Cannot identify the predecessor 3DS executable.')
                (install / 'ChestLink_3DS.3dsx').write_bytes(archive.read(names[0]))
        else:
            shutil.copy2(predecessor, install / 'ChestLink_3DS.3dsx')
    (app / 'config.json').write_text(json.dumps(dict(mode=mode, **config)))
    if normal:
        binary = ROOT / ('platform/nds/ChestLink_DS.nds' if console == 'ds'
                         else 'platform/3ds/ChestLink_3DS.3dsx')
        private_binary = area / binary.name
        shutil.copy2(binary, private_binary)
        binary = private_binary
        target = storage / ('_nds/pkmn-chest' if console == 'ds' else '3ds/PKSM')
        shutil.copytree(fixture['store'], target)
        settings = target / 'chest-link' if console == 'ds' else storage / '3ds/ChestLink'
        settings.mkdir(parents=True, exist_ok=True)
        (settings / 'server-ip.txt').write_text(config['ip'])
        (settings / 'server-pin.txt').write_text(str(config['pin']))
    process = ctx.processes.start(console + '-probe', ['stdbuf', '-oL', '-eL', program, str(binary)], area / 'emulator.log',
                                  cwd=ROOT, env=env)
    return dict(process=process, app=app, image=image, area=area, console=console)


def read_result(probe):
    log = probe['area'] / 'emulator.log'
    if probe['console'] == '3ds':
        log = probe['area'] / 'profile/data/azahar-emu/log/azahar_log.txt'
    if log.exists():
        accumulated = {}
        for line in log.read_text(errors='replace').splitlines():
            if 'CHESTLINK_E2E:' in line:
                try: accumulated.update(json.loads(line.split('CHESTLINK_E2E:', 1)[1]))
                except ValueError: pass
        if accumulated: return accumulated
    if probe['image'] is not None:
        if not probe['image'].exists(): return None
        env = os.environ.copy(); env['MTOOLS_SKIP_CHECK'] = '1'
        out = subprocess.run(['mcopy', '-i', str(probe['image']),
                              '::/chest-link-e2e/result.json', '-'],
                             capture_output=True, env=env, timeout=3)
        if out.returncode: return None
        data = out.stdout
    else:
        p = probe['app'] / 'result.json'
        if not p.is_file(): return None
        data = p.read_bytes()
    try: return json.loads(data)
    except (ValueError, UnicodeDecodeError): return None


def await_result(ctx, probe, *, timeout=90, on_stage=None):
    deadline = time.monotonic() + timeout
    last = None
    while time.monotonic() < deadline:
        result = read_result(probe)
        if result:
            state = result.get('stage')
            if state != last:
                last = state
                print(f"{probe['console']}: {state}", flush=True)
                if on_stage: on_stage(state, result)
            if result.get('status') in ('PASS', 'FAIL'):
                return result
        if probe['process'].poll() is not None:
            raise RuntimeError('Emulator exited without a structured probe result.')
        time.sleep(0.25)
    raise TimeoutError(f'Emulator probe timed out at stage {last}.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('console', choices=('ds', '3ds'))
    parser.add_argument('mode', choices=('preview', 'upload', 'update', 'fetch', 'direct_receive'))
    parser.add_argument('--ip')
    parser.add_argument('--save', default=os.environ.get('CHESTLINK_FIRERED_SAVE'))
    parser.add_argument('--manual-update', action='store_true',
                        help='Accept the DS update offer with the emulator-mapped A key.')
    args = parser.parse_args()
    if args.mode != 'update' and not args.save:
        parser.error('Set CHESTLINK_FIRERED_SAVE or --save.')
    if args.manual_update and (args.console != 'ds' or args.mode != 'update'):
        parser.error('--manual-update is supported only for DS update probes.')
    args.ip = args.ip or ('10.64.0.1' if args.console == 'ds' else '127.0.0.1')
    artifacts = RunArtifacts(ROOT / 'build/e2e')
    ctx = RunContext(artifacts, Environment.detect(), 180 if args.manual_update else 90,
                     build=False)
    ctx.scenario_name = args.console + '_' + args.mode + ('_firered' if args.mode != 'update' else '')
    print('Private run: ' + str(artifacts.path), flush=True)
    guard = PrivateSaveGuard(args.save) if args.mode != 'update' else None
    status = 'FAIL'
    try:
        if args.mode == 'update':
            fixture = {'store': artifacts.path / 'private/update-only-store',
                       'bank_sha256': None, 'boxes': 0, 'occupied': 0}
            fixture['store'].mkdir(parents=True, mode=0o700)
            print('Update-only fixture: empty private storage; no save data is used.', flush=True)
        else:
            fixture = create_firered_bank(args.save, artifacts.path / 'private/fixture')
            print(f"FireRed: {fixture['boxed']} boxed, {fixture['party']} party, checksums OK", flush=True)
        config = dict(ip=args.ip, pin=314159, port=40992)
        if args.manual_update:
            config['manual_update'] = 1
        if os.environ.get('CHESTLINK_PROBE_IDLE_MS'):
            config.update(ui_idle_ms=int(os.environ['CHESTLINK_PROBE_IDLE_MS']),
                          idle_listener=int(os.environ.get('CHESTLINK_PROBE_IDLE_LISTENER', '0')),
                          idle_draw=int(os.environ.get('CHESTLINK_PROBE_IDLE_DRAW', '1')))
        if args.mode != 'preview':
            start_pc_server(ctx, bind='0.0.0.0', tcp_port=free_port('0.0.0.0'))
            wait_server_ready(ctx)
            config['port'] = ctx.server['tcp_port']
        if args.mode == 'update':
            config['installed_version'] = (0 << 16) | (4 << 8) | 27
        item_id = None
        target = 1 if args.console == 'ds' else 2
        masks = [(1 << 30) - 1] * fixture['boxes']
        if args.mode in ('fetch', 'direct_receive'):
            item_id = host_upload(ctx, fixture)
            if args.mode == 'fetch':
                queued = api(ctx, '/api/requeue', dict(id=item_id, target=target, masks=masks))
                config.update(target=target, item_id=queued['id'])
            else:
                config['port'] = 40991
        probe = prepare(ctx, args.console, args.mode, fixture, config)
        direct_result = {}
        def on_stage(stage, _result):
            if stage == 'update_offer' and args.manual_update:
                from tests.e2e.ui_driver import NormalUIDriver
                driver = NormalUIDriver('ds', probe['area'])
                driver.wait(driver.dialog, 'update offer confirmation')
                time.sleep(.5)
                driver.key('x')
            if stage == 'listening' and args.mode == 'direct_receive':
                direct_result.update(api(ctx, '/api/send-direct', dict(
                    id=item_id, target=target, masks=masks, ip='127.0.0.1', pin=314159)))
        result = await_result(ctx, probe, on_stage=on_stage, timeout=180 if config.get('ui_idle_ms') else 90)
        (artifacts.path / 'private/probe-result.json').write_text(json.dumps(result, indent=2))
        status = result['status']
        if status != 'PASS':
            raise RuntimeError(result.get('error', 'Probe failed.'))
        if args.mode == 'preview' and (result.get('bank_sha256') != fixture['bank_sha256'] or
                                      result.get('valid_pk3') != fixture['occupied']):
            raise AssertionError('Emulator preview lost or changed private FireRed records.')
        if args.mode == 'upload':
            state = read_server_state(ctx)
            item = next(row for row in state['items'] if row['id'] == result['item_id'])
            if item['offer']['boxes'] != fixture['boxes'] or item['offer']['occupied'] != fixture['occupied']:
                raise AssertionError('Received FireRed counts differ.')
            received = ctx.server['data_root'] / 'items' / result['item_id'] / 'bank.bnk'
            if received.read_bytes() != fixture['bank'].read_bytes():
                raise AssertionError('Received FireRed bank bytes differ from the private source bank.')
            print('Server ACK and exact private bank bytes: PASS', flush=True)
        if args.mode in ('fetch', 'direct_receive'):
            if (result.get('bank_sha256') != fixture['bank_sha256'] or
                    result.get('valid_pk3') != fixture['occupied']):
                raise AssertionError('Emulator imported bank differs from the private FireRed fixture.')
            delivered_id = config['item_id'] if args.mode == 'fetch' else direct_result['id']
            metadata = json.loads((ctx.server['data_root'] / 'items' / delivered_id / 'meta.json').read_text())
            if not metadata['delivered']:
                raise AssertionError('PC did not record the confirmed delivery.')
            original = ctx.server['data_root'] / 'items' / item_id / 'bank.bnk'
            if original.read_bytes() != fixture['bank'].read_bytes():
                raise AssertionError('Original PC backup was changed by delivery.')
            print(f"Emulator bank SHA-256, {fixture['occupied']} valid PK3, delivery ACK, PC backup: PASS", flush=True)
        if args.mode == 'update':
            normal = ROOT / ('platform/nds/ChestLink_DS.nds' if args.console == 'ds'
                             else 'platform/3ds/ChestLink_3DS.3dsx')
            if result.get('update_state') != 2 or result.get('installed_sha256') != hashlib.sha256(normal.read_bytes()).hexdigest():
                raise AssertionError('Installed update does not match the verified normal executable.')
            if result.get('downloaded_bytes') != result.get('download_total_bytes') or result.get('download_total_bytes') != result.get('update_bytes'):
                raise AssertionError('Emulator progress did not report the full verified update stream.')
            if fixture['bank_sha256'] and result.get('bank_sha256') != fixture['bank_sha256']:
                raise AssertionError('Updater changed the private FireRed bank.')
            print('Update streamed, verified and installed in private emulator storage; executable SHA-256: PASS', flush=True)
        artifacts.record(ctx.scenario_name, 'PASS', 'EMULATOR', metrics={
            'boxes': fixture['boxes'], 'pokemon': fixture['occupied'],
            'private_fixture': 'FireRed' if fixture['bank_sha256'] else 'empty_update_storage',
            'structured_result': True})
    except Exception as exc:
        status = 'FAIL'
        print(type(exc).__name__ + ': ' + str(exc), flush=True)
        artifacts.record(ctx.scenario_name, 'FAIL', 'EMULATOR', reason=str(exc))
    finally:
        ctx.processes.stop_all()
        if guard:
            guard.verify_unchanged()
        artifacts.write_summary(args.mode, {'real_hardware_tested': False,
                                           'private_fixture': 'FireRed' if args.mode != 'update' else 'empty_update_storage'})
    print(status, ctx.scenario_name, flush=True)
    return 0 if status == 'PASS' else 1


if __name__ == '__main__':
    sys.exit(main())
