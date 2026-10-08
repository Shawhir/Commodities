"""Convenience wrapper: `python cli.py <command>` without installing the package."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from pmdash.cli import main  # noqa: E402

sys.exit(main())
