#!/usr/bin/env python3
"""Reproduce currents_by_activity from the shared public-CSV analysis."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.cli import figure_entrypoint


def configure(parser):
    parser.add_argument("--analysis-dir", help="Verified shared analysis directory")
    parser.add_argument("--dpi", type=int, default=180)


def run(args):
    from common.cycle_figures import run as render
    return render("currents_by_activity", args)


def main(argv=None):
    return figure_entrypoint("currents_by_activity", argv, runner=run, configure=configure)


if __name__ == "__main__":
    sys.exit(main())
