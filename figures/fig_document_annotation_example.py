#!/usr/bin/env python3
"""Clinical document annotation example. See the registry for the explicit implementation status."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.cli import figure_entrypoint


if __name__ == "__main__":
    sys.exit(figure_entrypoint("document_annotation_example"))
