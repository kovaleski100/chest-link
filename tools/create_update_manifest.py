#!/usr/bin/env python3
"""Write the version and digest that the PC server uses to publish an app."""
import hashlib
import json
from pathlib import Path
import re
import sys

if len(sys.argv) != 4:
    raise SystemExit("Uso: create_update_manifest.py APP VERSION.hpp SAIDA.json")
image, header, output = map(Path, sys.argv[1:])
text = header.read_text(encoding="utf-8")
parts = []
for name in ("MAJOR", "MINOR", "PATCH"):
    match = re.search(r"#define CHEST_LINK_VERSION_" + name + r"\s+(\d+)", text)
    if not match:
        raise SystemExit(f"Versao ausente em {header}")
    parts.append(int(match.group(1)))
if any(value > 255 for value in parts):
    raise SystemExit("Versao fora do limite")
version = (parts[0] << 16) | (parts[1] << 8) | parts[2]
if not version or not image.is_file():
    raise SystemExit("App 3DS ausente ou versao invalida")
manifest = {
    "format": 1,
    "version": version,
    "size": image.stat().st_size,
    "sha256": hashlib.sha256(image.read_bytes()).hexdigest(),
}
output.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
print(f"Atualizacao v{parts[0]}.{parts[1]}.{parts[2]}: {manifest['size']} bytes")
