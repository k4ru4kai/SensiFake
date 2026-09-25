"""Compatibility entry point; use app.py for new commands."""
from pathlib import Path
import runpy

if __name__ == "__main__":
    runpy.run_path(str(Path(__file__).resolve().with_name("app.py")), run_name="__main__")
