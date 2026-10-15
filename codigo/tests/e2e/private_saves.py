"""Read-only private fixture guard for user-provided native saves."""
import hashlib
import os
from pathlib import Path
import stat


class PrivateSaveError(RuntimeError):
    pass


class PrivateSaveGuard:
    def __init__(self, path):
        self.path = Path(path).expanduser().resolve(strict=True)
        info = self.path.stat()
        if not stat.S_ISREG(info.st_mode):
            raise PrivateSaveError("CHESTLINK_HGSS_SAVE precisa apontar para um arquivo regular.")
        self.before_stat = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        if info.st_size <= 0:
            raise PrivateSaveError("O save privado está vazio.")
        self.sha256 = self._hash()
        self.size_bytes = info.st_size

    def _hash(self):
        digest = hashlib.sha256()
        try:
            with self.path.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
        except OSError as exc:
            raise PrivateSaveError("Não foi possível ler o save privado.") from exc
        return digest.hexdigest()

    def verify_unchanged(self):
        try:
            info = self.path.stat()
        except OSError as exc:
            raise PrivateSaveError("O arquivo original sumiu ou ficou inacessível durante o teste.") from exc
        after_stat = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns)
        after_hash = self._hash()
        if after_stat != self.before_stat or after_hash != self.sha256:
            raise PrivateSaveError("O hash ou metadado do save original mudou durante o cenário.")
        return after_hash

    def copy_read_only(self, destination):
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        digest = hashlib.sha256()
        try:
            with self.path.open("rb") as source, destination.open("xb") as target:
                for chunk in iter(lambda: source.read(1024 * 1024), b""):
                    target.write(chunk)
                    digest.update(chunk)
                target.flush()
                os.fsync(target.fileno())
            os.chmod(destination, 0o400)
        except FileExistsError:
            raise PrivateSaveError("A cópia privada temporária já existe; não será sobrescrita.") from None
        except OSError as exc:
            destination.unlink(missing_ok=True)
            raise PrivateSaveError("Não foi possível criar a cópia temporária do save.") from exc
        if digest.hexdigest() != self.sha256:
            destination.unlink(missing_ok=True)
            raise PrivateSaveError("A cópia temporária do save não confere com o original.")
        self.verify_unchanged()
        return destination
