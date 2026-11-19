"""Ermöglicht den Aufruf als ``python -m s3_uploader``."""

import sys

from s3_uploader.cli import main

sys.exit(main())
