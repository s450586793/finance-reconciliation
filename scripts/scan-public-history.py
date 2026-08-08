from __future__ import annotations

import sys
from pathlib import Path

from public_scan import PublicScanError, scan_history


def main() -> int:
    if len(sys.argv) != 3:
        return 1
    try:
        scan_history(Path(sys.argv[1]), Path(sys.argv[2]))
    except PublicScanError:
        return 1
    print("public history scan passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
