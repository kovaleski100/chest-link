"""Unit tests for the opt-in, locally managed DS access point."""
import ipaddress
import unittest
from unittest.mock import Mock, patch

from server.ds_hotspot import DSHotspot, HotspotError


class DSHotspotTests(unittest.TestCase):
    def make_manager(self):
        manager = DSHotspot(40992)
        manager.available = True
        manager.nmcli = "/usr/bin/nmcli"
        manager.nft = "/usr/sbin/nft"
        manager.pkexec = "/usr/bin/pkexec"
        manager._choose_device_and_channel = Mock(return_value=("wlp1s0", 11))
        manager._choose_subnet = Mock(return_value=ipaddress.ip_network("10.231.42.0/24"))
        manager._firewall_add = Mock()
        manager._firewall_remove = Mock()
        manager._run = Mock(return_value="")
        return manager

    def test_profile_is_open_24ghz_shared_local_and_allows_peer_clients(self):
        manager = self.make_manager()
        state = manager.start()
        args = manager._run.call_args_list[0].args[0]
        self.assertEqual(state["ip"], "10.231.42.1")
        self.assertEqual(state["channel"], 11)
        self.assertIn(("802-11-wireless.band", "bg"), list(zip(args, args[1:])))
        self.assertIn(("802-11-wireless.ap-isolation", "0"), list(zip(args, args[1:])))
        self.assertNotIn("wifi-sec.key-mgmt", args)
        self.assertIn(("ipv4.method", "shared"), list(zip(args, args[1:])))
        self.assertIn(("ipv6.method", "disabled"), list(zip(args, args[1:])))
        self.assertNotIn("ipv4.shared-dhcp-range", args)
        self.assertEqual(state["ssid"], "ChestLink-DS")
        manager._firewall_add.assert_called_once_with(
            ipaddress.ip_network("10.231.42.0/24"), "wlp1s0")
        self.assertEqual(state["directPort"], 40991)

    def test_stop_deactivates_profile_then_removes_firewall(self):
        manager = self.make_manager()
        manager.start()
        state = manager.stop()
        self.assertFalse(state["running"])
        self.assertEqual(manager._run.call_count, 4)  # create, up, down, delete
        manager._firewall_remove.assert_called_once()

    def test_server_loopback_bind_disables_hotspot(self):
        manager = DSHotspot(40992, "127.0.0.1")
        self.assertFalse(manager.available)
        with self.assertRaisesRegex(HotspotError, "bind 0.0.0.0"):
            manager.start()

    def test_firewall_shares_internet_but_blocks_private_networks(self):
        manager = self.make_manager()
        captured = []
        manager._nft = captured.append
        manager._firewall_add = DSHotspot._firewall_add.__get__(manager)
        manager._firewall_add(ipaddress.ip_network("10.231.42.0/24"), "wlp1s0")
        rules = captured[0]
        self.assertIn("tcp dport 40992 accept", rules)
        self.assertIn("udp sport 68 udp dport 67 accept", rules)
        self.assertIn("ip saddr 10.231.42.0/24 udp dport 53 accept", rules)
        self.assertIn("ip saddr 10.231.42.0/24 tcp dport 53 accept", rules)
        self.assertIn("ct state established,related accept", rules)
        self.assertIn("ip daddr {", rules)
        self.assertIn("192.168.0.0/16", rules)
        self.assertIn("ip saddr 10.231.42.0/24 accept", rules)

    def test_active_ufw_gets_temporary_interface_scoped_mailbox_allow(self):
        manager = self.make_manager()
        manager.ufw = "/usr/sbin/ufw"
        calls = []

        def privileged(args, timeout=90):
            calls.append(args)
            return "Status: active" if len(calls) == 1 else "Rules updated"

        manager._privileged = privileged
        manager._ufw_add("wlp1s0", ipaddress.ip_network("10.231.42.0/24"))
        self.assertEqual(calls[0], ["/usr/sbin/ufw", "status"])
        self.assertEqual(calls[1][:5], ["/usr/sbin/ufw", "--force", "insert", "1", "allow"])
        self.assertEqual(calls[1][5:], [
            "in", "on", "wlp1s0", "from", "10.231.42.0/24", "to", "any",
            "port", "40992", "proto", "tcp", "comment", "ChestLink-DS-" + manager.table[-8:]])
        self.assertIsNotNone(manager._ufw_rule)
        manager._ufw_remove()
        self.assertEqual(calls[2][:5], ["/usr/sbin/ufw", "--force", "delete", "allow", "in"])
        self.assertIsNone(manager._ufw_rule)

    def test_inactive_ufw_is_left_unchanged(self):
        manager = self.make_manager()
        manager.ufw = "/usr/sbin/ufw"
        calls = []
        manager._privileged = lambda args, timeout=90: calls.append(args) or "Status: inactive"
        manager._ufw_add("wlp1s0", ipaddress.ip_network("10.231.42.0/24"))
        self.assertEqual(calls, [["/usr/sbin/ufw", "status"]])
        self.assertIsNone(manager._ufw_rule)

    @patch("server.ds_hotspot.subprocess.run")
    def test_failed_activation_removes_profile_and_network_rules(self, run):
        run.return_value.returncode = 0
        manager = self.make_manager()
        manager._run.side_effect = [None, HotspotError("activation rejected")]
        with self.assertRaisesRegex(HotspotError, "activation rejected"):
            manager.start()
        self.assertFalse(manager.state()["running"])
        manager._firewall_remove.assert_called_once()
        self.assertEqual(run.call_count, 2)


if __name__ == "__main__":
    unittest.main()
