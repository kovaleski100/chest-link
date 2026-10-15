"""Compile an isolated DS/3DS test pair without replacing release executables."""
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / 'build/e2e/console-probe'


def build():
    TARGET.mkdir(parents=True, exist_ok=True, mode=0o700)
    source = TARGET / 'source'
    source.mkdir(exist_ok=True)
    for name in ('source', 'include', 'assets', 'platform', 'third_party'):
        shutil.copytree(ROOT / name, source / name, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('build', '__pycache__', '*.nds',
                            '*.3dsx', '*.smdh', '*.elf', '*.map', 'release.json'))
    shutil.copy2(ROOT / 'version.mk', source / 'version.mk')
    (source / 'source/app.cpp').write_text((ROOT / 'tests/e2e/console_probe.cpp').read_text())
    jobs = []
    for console, image in (
        ('nds', 'docker.io/skylyrac/blocksds:slim-latest'),
        ('3ds', 'docker.io/devkitpro/devkitarm:20260610'),
    ):
        makefile = source / 'platform' / console / 'Makefile'
        contents = makefile.read_text()
        contents = contents.replace('COMMON :=', 'CXXFLAGS += -DCHEST_LINK_E2E\nCOMMON :=', 1)
        # Test binaries are never update artifacts or releases.
        if console == '3ds':
            contents = contents.replace('all: $(NAME).3dsx $(NAME).smdh release.json',
                                        'all: $(NAME).3dsx $(NAME).smdh')
        makefile.write_text(contents)
        log = (TARGET / f'{console}-build.log').open('w')
        command = ['podman', 'run', '--rm', '--pull=never', '-v', f'{source}:/work',
                   '-w', f'/work/platform/{console}', image, 'make', '-j2']
        jobs.append((console, subprocess.Popen(command, stdout=log, stderr=subprocess.STDOUT), log))
    failed = []
    for console, job, log in jobs:
        code = job.wait()
        log.close()
        print(f'{console} E2E build: ' + ('PASS' if code == 0 else f'FAIL ({code})'), flush=True)
        if code:
            failed.append(console)
    if failed:
        raise RuntimeError('Probe pair build failed: ' + ', '.join(failed))
    return source


if __name__ == '__main__':
    print(build(), flush=True)
