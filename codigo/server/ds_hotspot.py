"""Temporary DS-compatible access point with internet-only client routing."""
import ipaddress
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import tempfile
import threading


class HotspotError(RuntimeError):
    pass


class DSHotspot:
    """Create an open 2.4 GHz AP and share the PC's internet connection.

    NetworkManager's shared IPv4 mode supplies DHCP, DNS and NAT. A private
    nftables table limits access to this host to DNS, DHCP and the mailbox TCP
    port, and blocks forwarding to private/reserved IPv4 ranges. AP client
    isolation is disabled so consoles can connect directly on TCP 40991.
    """

    SUBNETS = (
        ipaddress.ip_network("10.231.42.0/24"),
        ipaddress.ip_network("10.231.43.0/24"),
        ipaddress.ip_network("172.31.237.0/24"),
        ipaddress.ip_network("192.168.253.0/24"),
    )

    def __init__(self, server_port=40992, server_bind="0.0.0.0"):
        self.server_port = int(server_port)
        self.table = "chest_link_ds_" + secrets.token_hex(4)
        self.nmcli = shutil.which("nmcli")
        self.nft = shutil.which("nft")
        self.ufw = shutil.which("ufw")
        self.pkexec = shutil.which("pkexec")
        self.available = (os.name == "posix" and self.nmcli is not None and
                          self.nft is not None and server_bind == "0.0.0.0")
        if server_bind != "0.0.0.0":
            self.reason = "A rede DS exige que o servidor escute em todas as interfaces (bind 0.0.0.0)."
        else:
            self.reason = "" if self.available else "Disponível no Linux com NetworkManager e nftables."
        self._lock = threading.RLock()
        self._running = False
        self._profile = ""
        self._device = ""
        self._ssid = ""
        self._address = ""
        self._channel = 0
        self._subnet = None
        self._ufw_rule = None

    @staticmethod
    def _run(args, timeout=20):
        try:
            result = subprocess.run(args, capture_output=True, text=True,
                                    timeout=timeout, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise HotspotError(f"Falha ao executar {Path(args[0]).name}: {exc}") from None
        if result.returncode:
            detail = (result.stderr or result.stdout).strip()
            raise HotspotError(detail or f"{Path(args[0]).name} encerrou com erro.")
        return result.stdout.strip()

    def _choose_device_and_channel(self):
        output = self._run([self.nmcli, "--terse", "--escape", "no", "--fields",
                            "DEVICE,TYPE,STATE", "device", "status"])
        devices = []
        for line in output.splitlines():
            columns = line.split(":", 2)
            if len(columns) == 3 and columns[1] in ("wifi", "802-11-wireless"):
                devices.append((columns[0], columns[2]))
        if not devices:
            raise HotspotError("Não encontrei uma placa Wi-Fi gerenciada pelo NetworkManager.")
        connected = next((row for row in devices if row[1].startswith("connected")), None)
        device = connected[0] if connected else next(
            (name for name, state in devices if state in ("disconnected", "connected (externally)")), None)
        if not device:
            raise HotspotError("A placa Wi-Fi está indisponível ou já está sendo controlada por outro serviço.")

        channel = 6
        if connected:
            link = self._run(["iw", "dev", device, "link"])
            match = re.search(r"^\s*freq:\s*(\d+)", link, re.MULTILINE)
            if not match:
                raise HotspotError("Não consegui identificar o canal Wi-Fi atual; não iniciei o hotspot.")
            frequency = int(match.group(1))
            if 2412 <= frequency <= 2472 and (frequency - 2407) % 5 == 0:
                channel = (frequency - 2407) // 5
            elif frequency == 2484:
                raise HotspotError(
                    "A rede DS não pode usar o canal 14. Conecta o PC a uma rede 2,4 GHz "
                    "nos canais 1–13, usa cabo ou desconecta o Wi-Fi antes de iniciar o hotspot.")
            else:
                raise HotspotError(
                    "A placa está conectada em 5 GHz e só pode manter um canal por vez. "
                    "Conecta o PC por cabo ou desconecta o Wi-Fi antes de iniciar a rede DS.")
        return device, channel

    def _choose_subnet(self):
        routes = ""
        ip_cmd = shutil.which("ip")
        if ip_cmd:
            try:
                routes = self._run([ip_cmd, "-4", "route", "show"])
            except HotspotError:
                routes = ""
        occupied = []
        for line in routes.splitlines():
            candidate = line.split(maxsplit=1)[0]
            if candidate == "default":
                continue
            try:
                occupied.append(ipaddress.ip_network(candidate, strict=False))
            except ValueError:
                continue
        for subnet in self.SUBNETS:
            if not any(subnet.overlaps(route) for route in occupied):
                return subnet
        raise HotspotError("Não encontrei uma sub-rede local livre para o hotspot DS.")

    def _nft(self, script):
        # Keep the privileged operation narrow and pass a private, short-lived
        # rules file; never interpolate user-controlled text into a shell.
        if os.geteuid() != 0 and not self.pkexec:
            raise HotspotError("É necessária autorização do sistema para isolar a rede DS (pkexec indisponível).")
        descriptor, filename = tempfile.mkstemp(prefix="chest-link-ds-", suffix=".nft")
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="ascii") as stream:
                stream.write(script)
            command = [self.nft, "-f", filename]
            if os.geteuid() != 0:
                command = [self.pkexec, *command]
            self._run(command, timeout=90)
        finally:
            try:
                os.unlink(filename)
            except FileNotFoundError:
                pass

    def _privileged(self, args, timeout=90):
        if os.geteuid() == 0:
            command = args
        else:
            if not self.pkexec:
                raise HotspotError("É necessária autorização do sistema para ajustar o firewall do hotspot DS.")
            command = [self.pkexec, *args]
        return self._run(command, timeout=timeout)

    def _ufw_add(self, device, subnet):
        if not self.ufw:
            return
        status = self._privileged([self.ufw, "status"])
        if not re.search(
                r"^(?:Status|Estado):\s*(?:active|ativo|ativa|activ[oa])\s*$",
                status, re.IGNORECASE | re.MULTILINE):
            return
        comment = "ChestLink-DS-" + self.table[-8:]
        rule = ["in", "on", device, "from", str(subnet), "to", "any",
                "port", str(self.server_port), "proto", "tcp", "comment", comment]
        self._privileged([self.ufw, "--force", "insert", "1", "allow", *rule])
        self._ufw_rule = rule

    def _ufw_remove(self):
        if not self._ufw_rule or not self.ufw:
            return
        rule = self._ufw_rule
        self._privileged([self.ufw, "--force", "delete", "allow", *rule])
        self._ufw_rule = None

    def _firewall_add(self, subnet, device):
        cidr = str(subnet)
        private_destinations = (
            "0.0.0.0/8, 10.0.0.0/8, 100.64.0.0/10, 127.0.0.0/8, "
            "169.254.0.0/16, 172.16.0.0/12, 192.0.0.0/24, "
            "192.0.2.0/24, 192.168.0.0/16, 198.18.0.0/15, "
            "198.51.100.0/24, 203.0.113.0/24, 224.0.0.0/4, "
            "240.0.0.0/4"
        )
        script = (
            f"table inet {self.table} {{\n"
            " chain input { type filter hook input priority -300; policy accept;\n"
            "  udp sport 68 udp dport 67 accept\n"
            f"  ip saddr {cidr} udp dport 53 accept\n"
            f"  ip saddr {cidr} tcp dport 53 accept\n"
            f"  ip saddr {cidr} tcp dport {self.server_port} accept\n"
            f"  ip saddr {cidr} drop\n"
            " }\n"
            " chain forward { type filter hook forward priority -190; policy accept;\n"
            "  ct state established,related accept\n"
            f"  ip saddr {cidr} ip daddr {{ {private_destinations} }} drop\n"
            f"  ip saddr {cidr} accept\n"
            " }\n"
            "}\n"
        )
        try:
            # nftables accept verdicts in one base chain do not bypass a later
            # UFW base chain. Add a narrowly scoped, temporary UFW exception
            # when UFW is active so its default-deny rules cannot reject the
            # DS mailbox connection.
            self._ufw_add(device, subnet)
            self._nft(script)
        except HotspotError as exc:
            try:
                self._ufw_remove()
            except HotspotError as cleanup_error:
                raise HotspotError(f"{exc} A regra temporária do UFW também não foi removida: {cleanup_error}") from None
            raise

    def _firewall_remove(self):
        errors = []
        try:
            self._nft(f"delete table inet {self.table}\n")
        except HotspotError as exc:
            errors.append(str(exc))
        try:
            self._ufw_remove()
        except HotspotError as exc:
            errors.append(str(exc))
        if errors:
            raise HotspotError("; ".join(errors))

    def state(self, can_manage=False):
        with self._lock:
            return dict(available=self.available, running=self._running,
                        ssid=self._ssid, ip=self._address, channel=self._channel,
                        reason=self.reason, canManage=bool(can_manage),
                        consolePort=self.server_port, directPort=40991)

    def start(self):
        with self._lock:
            if not self.available:
                raise HotspotError(self.reason)
            if self._running:
                return self.state(can_manage=True)

            try:
                device, channel = self._choose_device_and_channel()
                subnet = self._choose_subnet()
            except HotspotError as exc:
                self.reason = str(exc)
                raise
            host = str(subnet.network_address + 1)
            suffix = secrets.token_hex(2).upper()
            profile = f"Chest Link DS {suffix}"
            ssid = "ChestLink-DS"
            try:
                self._firewall_add(subnet, device)
            except HotspotError as exc:
                self.reason = f"Não foi possível instalar o isolamento de rede: {exc}"
                raise HotspotError(self.reason) from None
            created = False
            try:
                self._run([
                    self.nmcli, "connection", "add", "type", "wifi", "ifname", device,
                    "con-name", profile, "ssid", ssid,
                    "802-11-wireless.mode", "ap", "802-11-wireless.band", "bg",
                    "802-11-wireless.channel", str(channel),
                    "802-11-wireless.ap-isolation", "0",
                    "ipv4.method", "shared", "ipv4.addresses", f"{host}/24",
                    "ipv6.method", "disabled", "connection.autoconnect", "no",
                ])
                created = True
                self._run([self.nmcli, "--wait", "30", "connection", "up", "id", profile,
                           "ifname", device], timeout=40)
            except HotspotError as exc:
                active = False
                if created:
                    try:
                        down = subprocess.run([self.nmcli, "--wait", "10", "connection", "down", "id", profile],
                                              capture_output=True, text=True, timeout=15, check=False)
                        if down.returncode:
                            active = self._profile_active(profile)
                        if not active:
                            subprocess.run([self.nmcli, "connection", "delete", "id", profile],
                                           capture_output=True, text=True, timeout=15, check=False)
                    except (OSError, subprocess.TimeoutExpired, HotspotError):
                        try:
                            active = self._profile_active(profile)
                        except HotspotError:
                            active = True
                if active:
                    self._running, self._device, self._profile = True, device, profile
                    self._ssid, self._address, self._channel, self._subnet = ssid, host, channel, subnet
                    self.reason = "A ativação falhou, mas o ponto de acesso pode continuar ativo. " \
                                  "A proteção de rede foi mantida; tenta encerrar pelo botão."
                    raise HotspotError(self.reason) from None
                cleanup_error = ""
                try:
                    self._firewall_remove()
                except HotspotError as cleanup_exc:
                    cleanup_error = f" A regra de isolamento permaneceu ativa: {cleanup_exc}"
                self.reason = f"Falha ao iniciar a rede DS: {exc}.{cleanup_error}"
                raise HotspotError(
                    "Não foi possível iniciar a rede DS. "
                    "Confere a autorização do NetworkManager e se a placa aceita ponto de acesso. "
                    f"Detalhe: {self.reason}") from None

            self._running, self._device, self._profile = True, device, profile
            self._ssid, self._address, self._channel, self._subnet = ssid, host, channel, subnet
            self.reason = ""
            return self.state(can_manage=True)

    def stop(self):
        with self._lock:
            if not self._running:
                return self.state(can_manage=True)
            down_error = ""
            try:
                self._run([self.nmcli, "--wait", "15", "connection", "down", "id", self._profile], timeout=20)
            except HotspotError as exc:
                down_error = str(exc)
                try:
                    still_active = self._profile_active(self._profile)
                except HotspotError:
                    self.reason = "Não foi possível confirmar se o hotspot encerrou; o isolamento foi mantido. " + down_error
                    raise HotspotError(self.reason) from None
                if still_active:
                    self.reason = "Não encerrei o firewall porque o hotspot ainda está ativo: " + down_error
                    raise HotspotError(self.reason) from None
            errors = []
            if down_error:
                errors.append("NetworkManager: " + down_error)
            try:
                self._run([self.nmcli, "connection", "delete", "id", self._profile], timeout=20)
            except HotspotError as exc:
                errors.append(str(exc))
            try:
                self._firewall_remove()
            except HotspotError as exc:
                errors.append(str(exc))
            self._running, self._profile = False, ""
            self._device, self._ssid, self._address = "", "", ""
            self._channel, self._subnet = 0, None
            if errors:
                self.reason = "A rede foi encerrada, mas a limpeza do perfil/firewall precisa de atenção: " + "; ".join(errors)
                raise HotspotError(self.reason)
            self.reason = ""
            return self.state(can_manage=True)

    def _profile_active(self, profile):
        active = self._run([self.nmcli, "--terse", "--escape", "no", "--fields",
                            "NAME", "connection", "show", "--active"])
        return profile in active.splitlines()

    def close(self):
        if self._running:
            self.stop()
