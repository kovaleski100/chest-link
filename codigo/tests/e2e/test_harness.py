"""Small deterministic checks for the E2E support code itself."""
import hashlib
import json
import os
from pathlib import Path
import socket
import stat
import sys
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tests.e2e.normalized import compare_invariants, normalize_hgss
from tests.e2e.private_saves import PrivateSaveError, PrivateSaveGuard
from tests.e2e.process import ProcessRegistry
from tests.e2e.scenarios.common import create_synthetic_bank, free_port, tcp_port_available


class HarnessTests(unittest.TestCase):
    def test_synthetic_public_fixture_has_expected_bank_shape(self):
        with tempfile.TemporaryDirectory(prefix="chest-e2e-bank-") as folder:
            fixture = create_synthetic_bank(Path(folder) / "store")
            bank = fixture["bank"].read_bytes()
            self.assertEqual(len(bank), 16 + 10080)
            self.assertEqual(bank[:8], b"PKSMBANK")
            self.assertEqual(int.from_bytes(bank[8:12], "little"), 3)
            self.assertEqual(int.from_bytes(bank[12:16], "little"), 1)
            self.assertEqual(fixture["occupied"], 1)
            self.assertEqual(json.loads(fixture["names"].read_text()), [fixture["box_name"]])

    def test_private_save_copy_is_read_only_and_hash_guarded(self):
        with tempfile.TemporaryDirectory(prefix="chest-e2e-save-") as folder:
            root = Path(folder)
            source = root / "HeartGold.sav"
            source.write_bytes(b"synthetic private-save bytes")
            guard = PrivateSaveGuard(source)
            copy = guard.copy_read_only(root / "run" / "private" / "HeartGold.sav")
            self.assertEqual(copy.read_bytes(), source.read_bytes())
            self.assertFalse(stat.S_IMODE(copy.stat().st_mode) & 0o222)
            self.assertEqual(guard.verify_unchanged(), hashlib.sha256(source.read_bytes()).hexdigest())
            source.write_bytes(b"changed")
            with self.assertRaises(PrivateSaveError):
                guard.verify_unchanged()

    def test_normalizer_and_comparator_report_mismatch_fields_only(self):
        snapshot = {
            "game": "HeartGold", "gameVersion": "HG", "saveHash": "a" * 64,
            "trainer": {"name": {"value": "PRIVATE"}, "trainerId": {"value": 123},
                        "secretId": {"value": 456},
                        "playTime": {"value": {"totalSeconds": 7}}},
            "badges": {"johto": [{"name": "Zephyr", "acquired": True}], "kanto": []},
            "pokedex": {"seen": [1], "caught": [1]},
            "party": [None, {"species": 1}],
            "pokemon": [{"location": {"area": "box"}}],
        }
        normalized = normalize_hgss(snapshot)
        self.assertEqual(normalized["party_count"], 1)
        self.assertEqual(normalized["boxed_pokemon"], 1)
        self.assertEqual(compare_invariants([normalized, dict(normalized)]),
                         {key: True for key in normalized if key != "save_sha256"})
        changed = dict(normalized, pokedex_caught=[2])
        with self.assertRaisesRegex(ValueError, "pokedex_caught") as caught:
            compare_invariants([normalized, changed])
        self.assertNotIn("PRIVATE", str(caught.exception))
        self.assertNotIn("123", str(caught.exception))

    def test_process_registry_stops_process_group(self):
        with tempfile.TemporaryDirectory(prefix="chest-e2e-process-") as folder:
            manager = ProcessRegistry()
            process = manager.start("sleeper", [sys.executable, "-c", "import time; time.sleep(60)"],
                                    Path(folder) / "sleeper.log", cwd=ROOT, env=os.environ.copy())
            self.assertIsNone(process.poll())
            manager.stop_all()
            self.assertIsNotNone(process.poll())

    def test_tcp_port_preflight_detects_existing_listener(self):
        port = free_port("0.0.0.0")
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as listener:
            listener.bind(("0.0.0.0", port))
            listener.listen(1)
            self.assertFalse(tcp_port_available("0.0.0.0", port))
        self.assertTrue(tcp_port_available("0.0.0.0", port))

    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux process-group regression")
    def test_process_registry_stops_child_after_launcher_exits(self):
        with tempfile.TemporaryDirectory(prefix="chest-e2e-launcher-") as folder:
            manager = ProcessRegistry()
            pid_file = Path(folder) / "child.pid"
            launcher = (
                "import subprocess,sys,pathlib; "
                "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)']); "
                "pathlib.Path(sys.argv[1]).write_text(str(child.pid))"
            )
            process = manager.start("launcher", [sys.executable, "-c", launcher, str(pid_file)],
                                    Path(folder) / "launcher.log", cwd=ROOT, env=os.environ.copy())
            try:
                self.assertEqual(process.process.wait(timeout=5), 0)
                pid = int(pid_file.read_text())
                self.assertTrue(Path(f"/proc/{pid}").exists())
                manager.stop_all()
                stat_file = Path(f"/proc/{pid}/stat")
                self.assertTrue(not stat_file.exists() or stat_file.read_text().split()[2] == "Z")
            finally:
                manager.stop_all()


if __name__ == "__main__":
    unittest.main()
