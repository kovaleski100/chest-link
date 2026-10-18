"""Build optional local melonDS 1.1 with loopback TCP forwarding for DS input.

Downloads upstream open-source code only. Generated sources, compiler caches,
dependencies and executables stay in ignored build/e2e. Requires Podman.
"""
import hashlib
from pathlib import Path
import shutil
import subprocess
import tarfile
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parents[2]
AREA = ROOT / 'build/e2e/melonds-forward'
IMAGE = 'localhost/chestlink-melonds-e2e:1.1'
URL = 'https://codeload.github.com/melonDS-emu/melonDS/tar.gz/refs/tags/1.1'
SHA256 = '61e339bcb18a68a17485973637d972ea628c5624d7e6b8adf6870f895d5e26fd'
DOCKERFILE = '''FROM docker.io/devkitpro/devkitarm:20260610
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends build-essential cmake ninja-build pkg-config qt6-base-dev qt6-base-private-dev qt6-multimedia-dev qt6-svg-dev libqt6opengl6-dev libsdl2-dev libpcap-dev libenet-dev libarchive-dev libegl1-mesa-dev libzstd-dev libfaad-dev && rm -rf /var/lib/apt/lists/*
'''
PATCH = '''
    // Local E2E lab only: expose a guest listener through the NAT network.
    if (const char* value = std::getenv("CHESTLINK_DS_FORWARD"))
    {
        const int port = std::atoi(value);
        if (port > 0 && port < 65536)
        {
            in_addr host{}, guest{};
            host.s_addr = htonl(INADDR_LOOPBACK);
            guest.s_addr = htonl(kClientIP);
            const int status = slirp_add_hostfwd(Ctx, 0, host, port, guest, 40991);
            Log(LogLevel::Info, "E2E NAT forwarding: localhost:%d -> guest:40991 (%d)\\n", port, status);
        }
    }
'''


def build():
    AREA.mkdir(parents=True, exist_ok=True, mode=0o700)
    archive = AREA / 'upstream-1.1.tar.gz'
    if not archive.is_file():
        with urlopen(URL, timeout=60) as response:
            archive.write_bytes(response.read())
    if hashlib.sha256(archive.read_bytes()).hexdigest() != SHA256:
        raise RuntimeError('Unexpected upstream archive hash; inspect before rebuilding.')
    source = AREA / 'source'
    source.mkdir(exist_ok=True)
    with tarfile.open(archive) as tar:
        base = source.resolve()
        for member in tar.getmembers():
            target = (base / member.name).resolve()
            if not target.is_relative_to(base) or member.issym() or member.islnk():
                raise RuntimeError('Unsafe upstream archive entry.')
        tar.extractall(source)
    upstream = source / 'melonDS-1.1'
    slirp = upstream / 'src/net/Net_Slirp.cpp'
    contents = slirp.read_text()
    anchor = '    Ctx = slirp_new(&cfg, &cb, this);'
    if contents.count(anchor) != 1:
        raise RuntimeError('Upstream forwarding insertion point changed.')
    slirp.write_text(contents.replace(anchor, anchor + PATCH, 1))
    image_context = AREA / 'image'
    image_context.mkdir(exist_ok=True)
    (image_context / 'Dockerfile').write_text(DOCKERFILE)
    subprocess.run(['podman', 'build', '-t', IMAGE, str(image_context)], check=True)
    cmake = ['cmake', '-S', str(upstream), '-B', str(AREA / 'cache'), '-G', 'Ninja',
             '-DCMAKE_BUILD_TYPE=Release', '-DENABLE_WAYLAND=OFF', '-DENABLE_JIT=OFF',
             '-DENABLE_LTO_RELEASE=OFF', '-DENABLE_GDBSTUB=OFF', '-DPORTABLE=OFF']
    container = ['podman', 'run', '--rm', '--pull=never', '-v', f'{AREA}:{AREA}', IMAGE]
    subprocess.run(container + cmake, check=True)
    subprocess.run(container + ['cmake', '--build', str(AREA / 'cache'), '-j2'], check=True)
    shutil.copy2(AREA / 'cache/melonDS', AREA / 'melonDS')
    print(AREA / 'melonDS', flush=True)


if __name__ == '__main__': build()
