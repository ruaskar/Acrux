"""Enable `python -m keymd` (PATH-independent entry point)."""
import sys

from keymd.cli import main

if __name__ == "__main__":
    sys.exit(main())
