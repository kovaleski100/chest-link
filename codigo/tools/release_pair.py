"""Validate both built apps, not just a version pasted into their manifests."""
import hashlib
import json
from pathlib import Path
import re
import struct

APPS = {
    "DS/ChestLink_DS.nds": "platform/nds/ChestLink_DS.nds",
    "DS/release.json": "platform/nds/release.json",
    "3ds/ChestLink_3DS/ChestLink_3DS.3dsx": "platform/3ds/ChestLink_3DS.3dsx",
    "3ds/ChestLink_3DS/ChestLink_3DS.smdh": "platform/3ds/ChestLink_3DS.smdh",
    "3ds/ChestLink_3DS/release.json": "platform/3ds/release.json",
}


def shared_version(header):
    text = Path(header).read_text(encoding="utf-8")
    parts = []
    for name in ("MAJOR", "MINOR", "PATCH"):
        match = re.search(r"#define CHEST_LINK_VERSION_" + name + r"\s+(\d+)", text)
        if not match or not 0 <= int(match[1]) <= 255:
            raise ValueError(f"Versao invalida em {header}")
        parts.append(int(match[1]))
    code = (parts[0] << 16) | (parts[1] << 8) | parts[2]
    if not code:
        raise ValueError("A versao compartilhada nao pode ser zero")
    return code, ".".join(map(str, parts))


def validate_pair(root):
    root = Path(root)
    version, label = shared_version(root / "include/version.hpp")
    binaries = {}
    for relative in ("platform/nds/ChestLink_DS.nds", "platform/3ds/ChestLink_3DS.3dsx"):
        image = root / relative
        data = image.read_bytes()
        manifest = json.loads(image.with_name("release.json").read_text(encoding="utf-8"))
        expected = {"format": 1, "version": version, "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest()}
        if (manifest != expected or any(type(manifest.get(key)) is not int
                                       for key in ("format", "version", "size")) or
                not 1 <= len(data) <= 16 * 1024 * 1024):
            raise ValueError(f"Release fora de sincronia ou hash invalido: {image}")
        binaries[image.suffix] = data
    ds = binaries[".nds"]
    if len(ds) < 0x6c:
        raise ValueError("Cabecalho DS incompleto")
    banner, = struct.unpack_from("<I", ds, 0x68)
    title = ds[banner + 0x340:banner + 0x440].decode("utf-16le").split("\0")[0]
    if not banner or f"Boxes DS - PC - 3DS v{label}" not in title.splitlines():
        raise ValueError("Banner DS nao corresponde a versao compartilhada")
    smdh = (root / "platform/3ds/ChestLink_3DS.smdh").read_bytes()
    description = smdh[0x288:0x388].decode("utf-16le").split("\0")[0]
    if (not smdh.startswith(b"SMDH") or not description.endswith(f" v{label}") or
            not binaries[".3dsx"].startswith(b"3DSX") or smdh not in binaries[".3dsx"]):
        raise ValueError("Icone/descricao 3DS ou 3DSX nao corresponde a versao compartilhada")
    return version, label
