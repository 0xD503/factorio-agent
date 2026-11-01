#!/usr/bin/env python3
"""Entry point used by the `fx` and `fx.cmd` launchers: python3 fx.py <command>
..."""

import sys
from pathlib import Path

if sys.version_info < (3, 10):
    sys.exit(
        "fx: Python 3.10 or newer is required, this is "
        + sys.version.split()[0]
    )
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fxa.cli import main  # noqa: E402

sys.exit(main())
