import hashlib
import json
from pathlib import Path
import struct
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from create_update_manifest import create_manifest
from release_pair import APPS, validate_pair
import release_consoles as release


class ReleasePairTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="chest-link-pair-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "codigo"
        (self.root / "include").mkdir(parents=True)
        self.header = self.root / "include/version.hpp"
        self.header.write_text("#define CHEST_LINK_VERSION_MAJOR 0\n"
                               "#define CHEST_LINK_VERSION_MINOR 4\n"
                               "#define CHEST_LINK_VERSION_PATCH 26\n")
        smdh = bytearray(0x36c0)
        smdh[:4] = b"SMDH"
        description = "Boxes DS - PC - 3DS v0.4.26".encode("utf-16le")
        smdh[0x288:0x288 + len(description)] = description
        ds = bytearray(0xa40)
        struct.pack_into("<I", ds, 0x68, 0x200)
        title = "Chest Link\nBoxes DS - PC - 3DS v0.4.26\nChest Link contributors".encode("utf-16le")
        ds[0x540:0x540 + len(title)] = title
        for directory, filename, data in (("nds", "ChestLink_DS.nds", ds),
                                          ("3ds", "ChestLink_3DS.3dsx", b"3DSX" + smdh),
                                          ("3ds", "ChestLink_3DS.smdh", smdh)):
            path = self.root / "platform" / directory / filename
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            if path.suffix != ".smdh":
                create_manifest(path, self.header, path.with_name("release.json"))

    def test_matched_pair(self):
        self.assertEqual(validate_pair(self.root), (0x41a, "0.4.26"))

    def test_mismatched_versions_block_publication_before_writing(self):
        manifest = self.root / "platform/3ds/release.json"
        data = json.loads(manifest.read_text())
        data["version"] -= 1
        manifest.write_text(json.dumps(data))
        destination = Path(self.temp.name) / "published"
        with self.assertRaises(ValueError):
            release.publish(self.root, destination)
        self.assertFalse(destination.exists())

    def test_changed_binary_rejected(self):
        path = self.root / "platform/nds/ChestLink_DS.nds"
        path.write_bytes(path.read_bytes() + b"changed")
        with self.assertRaises(ValueError):
            validate_pair(self.root)

    def test_old_banner_cannot_be_relabelled_by_manifest(self):
        path = self.root / "platform/nds/ChestLink_DS.nds"
        path.write_bytes(path.read_bytes().replace("0.4.26".encode("utf-16le"),
                                                  "0.4.25".encode("utf-16le")))
        create_manifest(path, self.header, path.with_name("release.json"))
        with self.assertRaises(ValueError):
            validate_pair(self.root)

    def test_changed_external_3ds_icon_rejected(self):
        path = self.root / "platform/3ds/ChestLink_3DS.smdh"
        path.write_bytes(path.read_bytes() + b"changed")
        with self.assertRaises(ValueError):
            validate_pair(self.root)

    def test_missing_peer_and_existing_release_lock_are_safe(self):
        peer = self.root / "platform/3ds/ChestLink_3DS.3dsx"
        image = peer.read_bytes()
        peer.unlink()
        with self.assertRaises(FileNotFoundError):
            validate_pair(self.root)
        peer.write_bytes(image)
        destination = Path(self.temp.name) / "published"
        destination.mkdir()
        lock = destination / ".chest-link-console-release-in-progress"
        lock.write_text("another publisher")
        with self.assertRaises(FileExistsError):
            release.publish(self.root, destination)
        self.assertEqual(lock.read_text(), "another publisher")
        self.assertFalse((destination / "DS").exists())

    def test_publishes_both_and_checksums(self):
        destination = Path(self.temp.name) / "published"
        self.assertEqual(release.publish(self.root, destination), "0.4.26")
        for target, source in APPS.items():
            self.assertEqual((destination / target).read_bytes(), (self.root / source).read_bytes())
        for line in (destination / "SHA256SUMS.txt").read_text().splitlines():
            digest, name = line.split("  ", 1)
            self.assertEqual(digest, hashlib.sha256((destination / name).read_bytes()).hexdigest())
        self.assertFalse((destination / ".chest-link-console-release-in-progress").exists())

    def test_failed_replace_restores_previous_pair(self):
        destination = Path(self.temp.name) / "published"
        release.publish(self.root, destination)
        before = {target: (destination / target).read_bytes() for target in APPS}
        original = release.os.replace
        calls = 0

        def fail_once(source, target):
            nonlocal calls
            calls += 1
            if calls == 3:
                raise OSError("simulated filesystem failure")
            return original(source, target)

        with patch.object(release.os, "replace", fail_once), self.assertRaises(OSError):
            release.publish(self.root, destination)
        for target, data in before.items():
            self.assertEqual((destination / target).read_bytes(), data)
        self.assertFalse((destination / ".chest-link-console-release-in-progress").exists())

    def test_failed_rollback_retains_backups_and_release_lock(self):
        destination = Path(self.temp.name) / "published"
        release.publish(self.root, destination)
        stage = Path(tempfile.mkdtemp(prefix="chest-link-rollback-test-"))
        self.addCleanup(shutil.rmtree, stage)
        original = release.os.replace
        calls = 0

        def fail_repeatedly(source, target):
            nonlocal calls
            calls += 1
            if calls >= 3:
                raise OSError("simulated filesystem cannot restore")
            return original(source, target)

        with patch.object(release.tempfile, "mkdtemp", return_value=str(stage)), \
                patch.object(release.os, "replace", fail_repeatedly), \
                self.assertRaisesRegex(RuntimeError, "Backups preservados"):
            release.publish(self.root, destination)
        self.assertTrue((destination / ".chest-link-console-release-in-progress").exists())
        self.assertTrue((stage / "previous/DS/ChestLink_DS.nds").is_file())


if __name__ == "__main__":
    unittest.main()
