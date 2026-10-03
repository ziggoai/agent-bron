#!/usr/bin/env python3
"""Install the bundled Bron Terminal into a vault. The installer itself ships in core/Plugins/install_terminal.py."""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parents[1] / "core" / "Plugins" / "install_terminal.py"), run_name="__main__")
