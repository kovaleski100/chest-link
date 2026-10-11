#!/usr/bin/env python3
"""Package prebuilt native apps and complete source. Run after validation."""
import argparse
import hashlib
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("output", type=Path)
args = parser.parse_args()
apps = {
    "DS/ChestLink_DS.nds": ROOT / "platform/nds/ChestLink_DS.nds",
    "3ds/ChestLink_3DS/ChestLink_3DS.3dsx": ROOT / "platform/3ds/ChestLink_3DS.3dsx",
    "3ds/ChestLink_3DS/ChestLink_3DS.smdh": ROOT / "platform/3ds/ChestLink_3DS.smdh",
}
server = {
    "PC/servidor.py": ROOT / "server/chest_link_server.py",
    "PC/iniciar-linux.sh": ROOT / "server/iniciar-linux.sh",
    "PC/iniciar-windows.bat": ROOT / "server/iniciar-windows.bat",
    "PC/interface.py": ROOT / "server/interface.py",
    "PC/pokemon.py": ROOT / "server/pokemon.py",
}
for p in sorted((ROOT / "server/web").rglob("*")):
    if p.is_file():
        server["PC/web/" + str(p.relative_to(ROOT / "server/web"))] = p
files = {**apps, **server}
for p in apps.values():
    if not p.is_file():
        raise SystemExit(f"Compile primeiro: arquivo ausente {p}")
prefix = "Chest_Link_v0.3/"
args.output.parent.mkdir(parents=True, exist_ok=True)
extensions = {".cpp", ".hpp", ".h", ".py", ".md", ".txt", ".png", ".gif", ".sh", ".bat", ".html", ".css", ".js", ".json"}
with zipfile.ZipFile(args.output, "w", zipfile.ZIP_DEFLATED) as archive:
    for rel, p in files.items():
        archive.write(p, prefix + rel)
    archive.write(ROOT / "README.md", prefix + "LEIA-ME.md")
    sums = "".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {rel}\n" for rel, p in files.items())
    archive.writestr(prefix + "SHA256SUMS.txt", sums)
    if (ROOT / "VALIDACAO.txt").is_file():
        archive.write(ROOT / "VALIDACAO.txt", prefix + "VALIDACAO.txt")
    for p in sorted(ROOT.rglob("*")):
        rel = p.relative_to(ROOT)
        if not p.is_file() or "build" in rel.parts or "dados" in rel.parts or "__pycache__" in rel.parts or rel.parts[:3] == ("platform", "nds", "source"):
            continue
        if p.suffix not in extensions and p.name not in {"Makefile", "LICENSE", ".gitignore"}:
            continue
        archive.write(p, prefix + "codigo/" + str(rel))
with zipfile.ZipFile(args.output) as archive:
    bad = archive.testzip()
    if bad:
        raise SystemExit(f"ZIP invalido: {bad}")
print(args.output.resolve())
