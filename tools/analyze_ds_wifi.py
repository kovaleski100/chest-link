#!/usr/bin/env python3
"""Read-only analysis of this DS's WPA2/DHCP capture.

An explicitly selected NetworkManager profile supplies the PSK in memory.
Never prints/stores credentials, keys, or unrelated decrypted payloads.
Only authenticated DHCP for the selected DS and its ARP requests are reported.
This observes the wire, not what the DS hardware delivered to its software.
"""
import argparse
from datetime import datetime
import hashlib
import hmac
from pathlib import Path
import socket
import struct
import subprocess
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESCCM
from cryptography.hazmat.primitives.keywrap import aes_key_unwrap


def derive_ptk(pmk, ap, client, anonce, snonce):
    data = min(ap, client) + max(ap, client) + min(anonce, snonce) + max(anonce, snonce)
    return b"".join(hmac.new(pmk, b"Pairwise key expansion\0" + data + bytes([i]),
                             hashlib.sha1).digest() for i in range(4))[:64]


def packets(path):
    with Path(path).open("rb") as stream:
        header = stream.read(24)
        if len(header) != 24 or header[:4] != b"\xd4\xc3\xb2\xa1":
            raise ValueError("Expected little-endian classic PCAP")
        if struct.unpack_from("<I", header, 20)[0] != 127:
            raise ValueError("Expected radiotap PCAP")
        while True:
            header = stream.read(16)
            if len(header) < 16:
                return
            sec, usec, size, original = struct.unpack("<4I", header)
            raw = stream.read(size)
            if len(raw) < size:
                return  # Live writer has not completed this record yet.
            if size == original:
                yield sec + usec / 1_000_000, raw


def ieee_frame(raw):
    if len(raw) < 8:
        return b""
    length, present = struct.unpack_from("<HI", raw, 2)
    if length > len(raw):
        return b""
    offset = 8
    extension = present
    while extension & 0x80000000:
        if offset + 4 > length:
            return b""
        extension = struct.unpack_from("<I", raw, offset)[0]
        offset += 4
    if present & 1:  # TSFT is eight-byte aligned.
        offset = (offset + 7) & ~7
        offset += 8
    flags = raw[offset] if present & 2 and offset < length else 0
    if flags & 0x40:  # Bad FCS: not valid evidence of received contents.
        return b""
    return raw[length:-4] if flags & 0x10 else raw[length:]


def mic_valid(eapol, kck):
    copy = eapol[:81] + bytes(16) + eapol[97:]
    return hmac.compare_digest(hmac.new(kck, copy, hashlib.sha1).digest()[:16],
                               eapol[81:97])


def report_payload(timestamp, payload, client, direction):
    time = datetime.fromtimestamp(timestamp).astimezone().isoformat(timespec="milliseconds")
    if payload[:8] == bytes.fromhex("aaaa030000000806") and len(payload) >= 36:
        arp = payload[8:36]
        if arp[:6] == bytes.fromhex("000108000604"):
            op = struct.unpack_from("!H", arp, 6)[0]
            print(time, direction, "ARP", op,
                  "source", socket.inet_ntoa(arp[14:18]),
                  "target", socket.inet_ntoa(arp[24:28]))
        return
    if payload[:8] != bytes.fromhex("aaaa030000000800") or len(payload) < 36:
        return
    ip = payload[8:]
    ihl = (ip[0] & 15) * 4
    if ip[0] >> 4 != 4 or ihl < 20 or len(ip) < ihl + 8 or ip[9] != 17:
        return
    udp = ip[ihl:]
    source, target, length = struct.unpack_from("!3H", udp)
    if {source, target} != {67, 68} or length < 248 or length > len(udp):
        return
    bootp = udp[8:length]
    if bootp[28:34] != client or bootp[236:240] != bytes.fromhex("63825363"):
        return
    options = bootp[240:]
    i = 0
    while i < len(options):
        code = options[i]; i += 1
        if code == 255:
            return
        if code == 0:
            continue
        if i >= len(options):
            return
        size = options[i]; i += 1
        if i + size > len(options):
            return
        if code == 53 and size == 1:
            kind = {1: "Discover", 2: "Offer", 3: "Request", 5: "ACK", 6: "NAK"}.get(options[i], str(options[i]))
            print(time, direction, "DHCP", kind,
                  "xid", bootp[4:8].hex(), "yiaddr", socket.inet_ntoa(bootp[16:20]))
            return
        i += size


def analyze(paths, pmk, ap, client):
    anonce = ptk = gtk = None
    gtk_id = None
    verified = rejected = 0
    records = sorted(item for path in paths for item in packets(path))
    seen = set()
    for timestamp, raw in records:
        frame = ieee_frame(raw)
        if len(frame) < 24 or frame[0] & 12 != 8:
            continue
        incoming = frame[10:16] == ap and (frame[4:10] == client or frame[4] & 1)
        outgoing = frame[10:16] == client and frame[4:10] == ap
        if not incoming and not outgoing:
            continue
        qos = bool(frame[0] & 0x80)
        offset = 24 + (2 if qos else 0)
        if len(frame) < offset:
            continue
        payload = frame[offset:]
        if frame[1] & 0x40:
            if not ptk or len(payload) < 16:
                continue
            header = payload[:8]
            group = incoming and bool(frame[4] & 1)
            if group and (not gtk or header[3] >> 6 != gtk_id):
                continue
            key = gtk if group else ptk[32:48]
            priority = frame[24] & 15 if qos else 0
            nonce = bytes([priority]) + frame[10:16] + bytes(header[i] for i in (7, 6, 5, 4, 1, 0))
            aad = bytes([frame[0] & 0x8f, frame[1] & 0xc7]) + frame[4:22] + bytes([frame[22] & 15, 0])
            if qos:
                aad += bytes([priority, 0])
            try:
                payload = AESCCM(key, tag_length=8).decrypt(nonce, payload[8:], aad)
                verified += 1
            except InvalidTag:
                rejected += 1
                continue
            signature = (frame[10:16], bytes(header), payload)
            if signature not in seen:
                seen.add(signature)
                report_payload(timestamp, payload, client, "AP->DS" if incoming else "DS->AP")
            continue
        if payload[:8] != bytes.fromhex("aaaa03000000888e") or len(payload) < 107:
            continue
        eapol = payload[8:]
        length = 4 + struct.unpack_from("!H", eapol, 2)[0]
        if length < 99 or length > len(eapol):
            continue
        eapol = eapol[:length]
        info = struct.unpack_from("!H", eapol, 5)[0]
        if incoming and info & 0x188 == 0x88:
            if anonce != eapol[17:49]:
                ptk = gtk = None
                anonce = eapol[17:49]
        elif outgoing and info & 0x388 == 0x108 and anonce:
            candidate = derive_ptk(pmk, ap, client, anonce, eapol[17:49])
            if mic_valid(eapol, candidate[:16]):
                ptk = candidate
        elif incoming and ptk and info & 0x13c8 == 0x13c8 and mic_valid(eapol, ptk[:16]):
            try:
                data = aes_key_unwrap(ptk[16:32], eapol[99:])
            except ValueError:
                continue
            i = 0
            while i + 2 <= len(data):
                code, size = data[i:i + 2]; i += 2
                if i + size > len(data):
                    break
                if code == 221 and size == 22 and data[i:i + 4] == bytes.fromhex("000fac01"):
                    gtk_id = data[i + 4] & 3
                    gtk = data[i + 6:i + 22]
                    break
                i += size
    print("Authenticated CCMP frames:", verified, "MIC rejected:", rejected,
          "handshake key validated:", bool(ptk))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True)
    parser.add_argument("--ssid", required=True)
    parser.add_argument("--ap", required=True)
    parser.add_argument("--client", required=True)
    parser.add_argument("pcaps", nargs="+")
    args = parser.parse_args()
    def setting(name, secrets=False):
        cmd = ["nmcli"] + (["--show-secrets"] if secrets else [])
        cmd += ["-g", name, "connection", "show", args.profile]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode:
            raise SystemExit("NetworkManager setting unavailable; no secrets logged")
        return result.stdout.rstrip("\n")
    if setting("802-11-wireless.ssid") != args.ssid:
        raise SystemExit("Profile SSID mismatch")
    password = setting("802-11-wireless-security.psk", True)
    if not password:
        raise SystemExit("Saved network secret unavailable")
    pmk = bytes.fromhex(password) if len(password) == 64 else hashlib.pbkdf2_hmac(
        "sha1", password.encode(), args.ssid.encode(), 4096, 32)
    del password
    analyze(args.pcaps, pmk, bytes.fromhex(args.ap.replace(":", "")),
            bytes.fromhex(args.client.replace(":", "")))
