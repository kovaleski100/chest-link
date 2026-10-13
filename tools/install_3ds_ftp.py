#!/usr/bin/env python3
"""Install a verified 3DS release via FTP, retaining the previous executable."""
import argparse
from ftplib import FTP, all_errors
import hashlib
from io import BytesIO
import json
from pathlib import Path, PurePosixPath
import uuid

from release_pair import validate_pair

APP, ICON = "ChestLink_3DS.3dsx", "ChestLink_3DS.smdh"


def remote_digest(ftp, path):
    digest = hashlib.sha256()
    size = 0

    def consume(block):
        nonlocal size
        size += len(block)
        if size > 16 * 1024 * 1024:
            raise RuntimeError("Arquivo FTP excede o limite de tamanho")
        digest.update(block)

    ftp.retrbinary("RETR " + path, consume, blocksize=65536)
    return size, digest.hexdigest()


def install(ftp, app, icon, version, directory="/3ds/ChestLink_3DS", expected_current=None):
    if (not directory.startswith("/3ds/") or
            any(part == ".." for part in PurePosixPath(directory).parts) or
            any(char in directory for char in "\r\n\\*?")):
        raise ValueError("Pasta FTP invalida; informe a pasta existente do app em /3ds")
    directory = str(PurePosixPath(directory))
    path = lambda name: directory + "/" + name
    names = {PurePosixPath(name).name for name in ftp.nlst(directory)}
    if APP not in names:
        raise RuntimeError("App atual nao encontrado na pasta FTP; nada foi alterado")
    images = {APP: app, ICON: icon}
    fingerprints = {name: (len(data), hashlib.sha256(data).hexdigest())
                    for name, data in images.items()}
    originals = {name: remote_digest(ftp, path(name)) for name in images if name in names}
    if expected_current and originals[APP][1] not in (expected_current, fingerprints[APP][1]):
        raise RuntimeError("App no console mudou desde a verificacao; nada foi alterado")
    if originals == fingerprints:
        return {"installed": False, "version": version, "path": path(APP)}

    for i in range(100):
        suffix = ".previous" + (str(i) if i else "")
        backups = {name: path(name + suffix) for name in originals}
        receipt = path(APP + suffix + ".cleanup.json")
        if all(PurePosixPath(item).name not in names
               for item in [*backups.values(), receipt]):
            break
    else:
        raise RuntimeError("Sem nome livre para preservar o app anterior; nada foi alterado")

    token = uuid.uuid4().hex[:12]
    staged = {name: path(name + ".upload-" + token) for name in images}
    owned = []
    moved, installed = {}, []
    completed = rollback_failed = False
    try:
        for name, data in images.items():
            owned.append(staged[name])
            ftp.storbinary("STOR " + staged[name], BytesIO(data), blocksize=16384)
            if remote_digest(ftp, staged[name]) != fingerprints[name]:
                raise RuntimeError("SHA-256 do arquivo enviado nao confere; app atual preservado")
        record = json.dumps({"format": 1, "version": version,
                             "installed": fingerprints[APP][1],
                             "backup": originals[APP][1]}, sort_keys=True).encode()
        owned.append(receipt)
        ftp.storbinary("STOR " + receipt, BytesIO(record))
        if remote_digest(ftp, receipt) != (len(record), hashlib.sha256(record).hexdigest()):
            raise RuntimeError("Recibo de backup FTP nao confere; app atual preservado")
        for name, fingerprint in originals.items():
            if remote_digest(ftp, path(name)) != fingerprint:
                raise RuntimeError("Arquivo no console mudou durante o envio; instalacao cancelada")
        for name in images:
            if name in originals:
                ftp.rename(path(name), backups[name])
                moved[name] = backups[name]
            ftp.rename(staged[name], path(name))
            installed.append(name)
        for name, fingerprint in fingerprints.items():
            if remote_digest(ftp, path(name)) != fingerprint:
                raise RuntimeError("Verificacao final FTP falhou; restaurando copia anterior")
        completed = True
        return {"installed": True, "version": version, "path": path(APP),
                "backup": backups[APP], "sha256": fingerprints[APP][1]}
    except BaseException as error:
        for name in reversed(list(images)):
            try:
                if name in installed:
                    ftp.rename(path(name), staged[name])
                if name in moved:
                    ftp.rename(moved[name], path(name))
            except all_errors:
                rollback_failed = True
        if rollback_failed:
            raise RuntimeError("FTP interrompido ao restaurar. Backups preservados: " +
                               ", ".join(moved.values())) from error
        raise
    finally:
        if not rollback_failed:
            for item in owned:
                if completed and item == receipt:
                    continue  # The new app validates this receipt before cleaning its backup.
                try:
                    ftp.delete(item)
                except all_errors:
                    pass  # Already renamed, absent, or connection closed; never delete old backups.


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("host")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--directory", default="/3ds/ChestLink_3DS")
    parser.add_argument("--expected-current-sha256")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    version, label = validate_pair(root)
    ftp = FTP()
    try:
        ftp.connect(args.host, args.port, timeout=10)
        ftp.login()
        result = install(ftp, (root / "platform/3ds" / APP).read_bytes(),
                         (root / "platform/3ds" / ICON).read_bytes(), version,
                         args.directory, args.expected_current_sha256)
        print(f"3DS v{label}: " + ("instalado e SHA-256 conferido" if result["installed"] else "ja instalado"))
        print(json.dumps(result, sort_keys=True))
    except all_errors + (RuntimeError, ValueError) as error:
        raise SystemExit(str(error))
    finally:
        ftp.close()


if __name__ == "__main__":
    main()
