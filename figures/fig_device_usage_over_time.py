#!/usr/bin/env python3
"""Calendar figure rendered only from separately approved aggregate inputs."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from common.cli import figure_entrypoint


def configure(parser):
    parser.add_argument("--aggregates-dir", help="Separate calendar aggregate input directory")
    parser.add_argument("--allow-review-only", action="store_true", help="Render locally for review; not permission to publish")
    parser.add_argument("--dpi", type=int, default=180)


def run(args):
    from common.calendar_figures import run as render
    return render("device_usage_over_time", args)


def main(argv=None):
    return figure_entrypoint("device_usage_over_time", argv, runner=run, configure=configure)


if __name__=="__main__":
    sys.exit(main())
