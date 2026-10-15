#!/usr/bin/env python3
"""Build, verify and publish DS + 3DS together. Never release one alone."""
import argparse
import hashlib
from pathlib import Path
import os
import shutil
import subprocess
import tempfile

from create_update_manifest import create_manifest
from release_pair import APPS, validate_pair

ROOT = Path(__file__).resolve().parents[1]
IMAGES = {"nds": "docker.io/skylyrac/blocksds:slim-latest",
          "3ds": "docker.io/devkitpro/devkitarm:20260610"}


def build(root=ROOT, native=False, engine="podman"):
    jobs = []
    try:
        for console, image in IMAGES.items():
            if native:
                command = ["make", "-C", str(root / "platform" / console)]
            else:
                command = [engine, "run", "--rm", "-v", f"{root}:/work",
                           "-w", f"/work/platform/{console}", image, "make"]
            jobs.append(subprocess.Popen(command))
        if any([job.wait() for job in jobs]):
            raise RuntimeError("Compilacao falhou; nenhum app foi publicado")
    finally:
        for job in jobs:
            job.wait()
    for console, extension in (("nds", "nds"), ("3ds", "3dsx")):
        directory = root / "platform" / console
        name = "ChestLink_DS" if console == "nds" else "ChestLink_3DS"
        create_manifest(directory / f"{name}.{extension}", root / "include/version.hpp",
                        directory / "release.json")
    return validate_pair(root)


def publish(root=ROOT, destination=None):
    root = Path(root)
    destination = Path(destination) if destination else root.parent
    _, label = validate_pair(root)
    destination.mkdir(parents=True, exist_ok=True)
    lock = destination / ".chest-link-console-release-in-progress"
    stage = Path(tempfile.mkdtemp(prefix="chest-link-release-"))
    changed = []
    locked = False
    rollbackFailed = False
    try:
        with lock.open("x", encoding="utf-8") as handle:
            handle.write(label + "\n")
        locked = True
        staged = {}
        for target, source in APPS.items():
            temporary = stage / target
            temporary.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(root / source, temporary)
            staged[target] = temporary
        sums = destination / "SHA256SUMS.txt"
        entries = {}
        if sums.is_file():
            for line in sums.read_text(encoding="utf-8").splitlines():
                digest, name = line.split("  ", 1)
                entries[name] = digest
        for name, temporary in staged.items():
            entries[name] = hashlib.sha256(temporary.read_bytes()).hexdigest()
        staged["SHA256SUMS.txt"] = stage / "SHA256SUMS.txt"
        staged["SHA256SUMS.txt"].write_text(
            "".join(f"{digest}  {name}\n" for name, digest in entries.items()), encoding="utf-8")
        for name, temporary in staged.items():
            target = destination / name
            target.parent.mkdir(parents=True, exist_ok=True)
            backup = stage / "previous" / name
            if target.exists():
                backup.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(target, backup)
            # Stage on the target filesystem for atomic replace across mounts.
            pending = target.with_name(target.name + ".release-download")
            record = [target, backup, pending, False]
            changed.append(record)
            shutil.copy2(temporary, pending)
            os.replace(pending, target)
            record[3] = True
    except BaseException as error:
        for target, backup, pending, replaced in reversed(changed):
            try:
                if replaced:
                    if backup.exists():
                        shutil.copy2(backup, pending)
                        os.replace(pending, target)
                    elif target.exists():
                        target.unlink()
                if pending.exists():
                    pending.unlink()
            except OSError:
                rollbackFailed = True
        if rollbackFailed:
            raise RuntimeError(f"Falha ao restaurar o par. Backups preservados em {stage}; "
                               f"a trava {lock} foi mantida para impedir nova publicacao.") from error
        raise
    finally:
        # Only the staging folder and marker created by this run.
        if not rollbackFailed:
            shutil.rmtree(stage)
            if locked:
                lock.unlink()
    return label


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--native", action="store_true", help="Usar os dois SDKs instalados no host")
    parser.add_argument("--engine", default="podman")
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument("--publish-only", action="store_true", help="Validar e publicar o par ja compilado")
    args = parser.parse_args()
    if args.build_only and args.publish_only:
        parser.error("Escolha build-only ou publish-only")
    if not args.publish_only:
        _, label = build(native=args.native, engine=args.engine)
    else:
        _, label = validate_pair(ROOT)
    if not args.build_only:
        publish()
    print(f"DS e 3DS v{label}: par verificado" + (" e publicado" if not args.build_only else ""))


if __name__ == "__main__":
    main()
