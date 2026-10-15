#!/usr/bin/env python3
"""Run the local lab melonDS with optional loopback -> guest TCP forwarding."""
import os
from pathlib import Path
import pwd
import sys

ROOT = Path(__file__).resolve().parents[2]
binary = Path(os.environ.get('CHESTLINK_MELONDS_FORWARD_BINARY',
                            ROOT / 'build/e2e/melonds-forward/melonDS'))
if not binary.is_file():
    raise SystemExit('Build the local melonDS forwarding binary first; see the E2E README.')
command = ['podman', 'run', '--rm', '--pull=never', '--network=host',
           '-v', f'{ROOT}:{ROOT}:ro',
           '-v', f'{ROOT / "build/e2e"}:{ROOT / "build/e2e"}:rw',
           '-v', '/tmp/.X11-unix:/tmp/.X11-unix:ro',
           '-e', 'QT_QPA_PLATFORM=xcb', '-e', 'XDG_RUNTIME_DIR=/tmp/qt-runtime']
if os.environ.get('CHESTLINK_E2E_CONTAINER_ID'):
    command.extend(('--cidfile', os.environ['CHESTLINK_E2E_CONTAINER_ID']))
for key in ('DISPLAY', 'HOME', 'XDG_CONFIG_HOME', 'XDG_DATA_HOME', 'XDG_CACHE_HOME',
            'CHESTLINK_DS_FORWARD'):
    if key in os.environ: command.extend(('-e', key + '=' + os.environ[key]))
authority = os.environ.get('XAUTHORITY')
if authority and Path(authority).is_file():
    command.extend(('-v', authority + ':/tmp/chestlink-xauthority:ro',
                    '-e', 'XAUTHORITY=/tmp/chestlink-xauthority'))
command.extend((os.environ.get('CHESTLINK_MELONDS_FORWARD_IMAGE',
                              'localhost/chestlink-melonds-e2e:1.1'),
                'stdbuf', '-oL', '-eL', str(binary), *sys.argv[1:]))
# The emulator uses the isolated HOME above; Podman must see its existing
# host-side image store instead of looking inside that temporary profile.
podman_env = os.environ.copy()
host_home = Path(pwd.getpwuid(os.getuid()).pw_dir)
podman_env.update(HOME=str(host_home), XDG_CONFIG_HOME=str(host_home / '.config'),
                  XDG_DATA_HOME=str(host_home / '.local/share'),
                  XDG_CACHE_HOME=str(host_home / '.cache'))
os.execvpe('podman', command, podman_env)
