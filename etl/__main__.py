"""`python -m etl` entry point. Everything real lives in `cli.py`."""

import sys

from .cli import main

sys.exit(main())
