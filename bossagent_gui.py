"""Windows GUI executable entry point for BossAgent."""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

from main import run_gui


if __name__ == "__main__":
    try:
        raise SystemExit(run_gui())
    except BaseException:
        base_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path(__file__).resolve().parent
        (base_dir / "BossAgent.error.log").write_text(traceback.format_exc(), encoding="utf-8")
        raise
