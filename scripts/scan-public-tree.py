from __future__ import annotations

import sys
from pathlib import Path

from public_scan import scan_tree


def main() -> int:
    if len(sys.argv) != 3:
        return 1
    try:
        scan_tree(Path(sys.argv[1]), Path(sys.argv[2]))
    except ValueError:
        return 1
    print("public tree scan passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
