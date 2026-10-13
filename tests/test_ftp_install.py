from ftplib import error_perm
import hashlib
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from install_3ds_ftp import APP, ICON, install


class FakeFTP:
    def __init__(self):
        self.base = "/3ds/ChestLink_3DS/"
        self.files = {self.base + APP: b"old app", self.base + ICON: b"old icon",
                      self.base + "user.bnk": b"bank never touched"}
        self.corrupt = False
        self.rename_failure = self.restore_failure = False

    def nlst(self, directory):
        return [path for path in self.files if path.startswith(directory + "/")]

    def retrbinary(self, command, callback, blocksize=8192):
        callback(self.files[command[5:]])

    def storbinary(self, command, source, blocksize=8192):
        path = command[5:]
        self.files[path] = source.read()
        if self.corrupt and APP + ".upload-" in path:
            self.files[path] += b"changed during transfer"

    def rename(self, source, target):
        if self.rename_failure and ICON + ".upload-" in source:
            raise error_perm("550 simulated install failure")
        if self.restore_failure and APP + ".previous" in source:
            raise error_perm("550 simulated restore failure")
        if target in self.files:
            raise error_perm("550 do not overwrite")
        self.files[target] = self.files.pop(source)

    def delete(self, path):
        if path not in self.files:
            raise error_perm("550 absent")
        del self.files[path]


class FTPInstallTests(unittest.TestCase):
    def test_verified_install_preserves_old_app_and_receipt(self):
        ftp = FakeFTP()
        ftp.files[ftp.base + APP + ".previous"] = b"earlier backup"
        result = install(ftp, b"new app", b"new icon", 0x41b)
        self.assertTrue(result["installed"])
        self.assertEqual(ftp.files[ftp.base + APP], b"new app")
        self.assertEqual(ftp.files[result["backup"]], b"old app")
        self.assertEqual(ftp.files[ftp.base + APP + ".previous"], b"earlier backup")
        receipt = json.loads(ftp.files[result["backup"] + ".cleanup.json"])
        self.assertEqual(receipt, {"format": 1, "version": 0x41b,
                                 "installed": hashlib.sha256(b"new app").hexdigest(),
                                 "backup": hashlib.sha256(b"old app").hexdigest()})
        self.assertEqual(ftp.files[ftp.base + "user.bnk"], b"bank never touched")
        self.assertFalse(any(".upload-" in path for path in ftp.files))

    def test_corruption_never_replaces_originals(self):
        ftp = FakeFTP()
        before = dict(ftp.files)
        ftp.corrupt = True
        with self.assertRaisesRegex(RuntimeError, "SHA-256"):
            install(ftp, b"new app", b"new icon", 0x41b)
        self.assertEqual(ftp.files, before)

    def test_failed_icon_install_restores_both_originals(self):
        ftp = FakeFTP()
        before = dict(ftp.files)
        ftp.rename_failure = True
        with self.assertRaises(error_perm):
            install(ftp, b"new app", b"new icon", 0x41b)
        self.assertEqual(ftp.files, before)

    def test_failed_restore_keeps_recoverable_backup(self):
        ftp = FakeFTP()
        ftp.rename_failure = ftp.restore_failure = True
        with self.assertRaisesRegex(RuntimeError, "Backups preservados"):
            install(ftp, b"new app", b"new icon", 0x41b)
        self.assertEqual(ftp.files[ftp.base + APP + ".previous"], b"old app")
        self.assertEqual(ftp.files[ftp.base + "user.bnk"], b"bank never touched")

    def test_different_current_app_is_not_overwritten(self):
        ftp = FakeFTP()
        before = dict(ftp.files)
        with self.assertRaisesRegex(RuntimeError, "mudou desde"):
            install(ftp, b"new app", b"new icon", 0x41b, expected_current="0" * 64)
        self.assertEqual(ftp.files, before)

    def test_repeat_install_is_read_only(self):
        ftp = FakeFTP()
        install(ftp, b"new app", b"new icon", 0x41b)
        before = dict(ftp.files)
        self.assertFalse(install(ftp, b"new app", b"new icon", 0x41b)["installed"])
        self.assertEqual(ftp.files, before)


if __name__ == "__main__":
    unittest.main()
