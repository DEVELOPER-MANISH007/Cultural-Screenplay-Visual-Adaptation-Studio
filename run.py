"""Convenience launcher: `python run.py` starts the Streamlit app."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main() -> int:
    cmd = [sys.executable, "-m", "streamlit", "run", str(ROOT / "app" / "main.py")]
    return subprocess.call(cmd, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
