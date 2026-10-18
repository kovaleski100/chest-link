#!/usr/bin/env python3
"""Launch the single packaged server implementation from the PC folder."""
from pathlib import Path
import sys


pc_dir = Path(sys.argv[0]).absolute().parent
source_dir = pc_dir.parent / "codigo" / "server"


def main():
    sys.path.insert(0, str(source_dir))
    if not any(arg == "--data" or arg.startswith("--data=") for arg in sys.argv[1:]):
        sys.argv.extend(("--data", str(pc_dir / "dados")))
    from chest_link_server import main as run_server
    return run_server()


if __name__ == "__main__":
    raise SystemExit(main())
