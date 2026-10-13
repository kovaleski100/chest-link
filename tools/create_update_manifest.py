#!/usr/bin/env python3
"""Write the version and digest that the PC server uses to publish an app."""
import hashlib
import json
from pathlib import Path
import sys
from release_pair import shared_version

def create_manifest(image, header, output):
    image, header, output = map(Path, (image, header, output))
    version, label = shared_version(header)
    if not image.is_file():
        raise ValueError(f"App ausente: {image}")
    manifest = {"format": 1, "version": version, "size": image.stat().st_size,
                "sha256": hashlib.sha256(image.read_bytes()).hexdigest()}
    output.write_text(json.dumps(manifest, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Atualizacao v{label}: {manifest['size']} bytes")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("Uso: create_update_manifest.py APP VERSION.hpp SAIDA.json")
    create_manifest(*sys.argv[1:])
