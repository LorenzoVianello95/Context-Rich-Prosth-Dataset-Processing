#!/usr/bin/env python3
"""Discover figure entry points or check the external public dataset contract."""

import argparse
import importlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common.cli import figure_entrypoint
from common.metadata import load_public_metadata, load_registry, metadata_summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    selection = parser.add_mutually_exclusive_group(required=True)
    selection.add_argument("--list", action="store_true", help="List all figure scripts and their current status")
    selection.add_argument("--check-dataset", action="store_true", help="Check only the public metadata/schema contract")
    selection.add_argument("--figure", help="Dispatch to one figure entry point")
    args, extra = parser.parse_known_args(argv)
    if args.figure:
        figures = {f["id"] for f in load_registry()["figures"]}
        if args.figure not in figures:
            parser.error("Unknown figure ID; use --list")
        figure = next(f for f in load_registry()["figures"] if f["id"] == args.figure)
        module = importlib.import_module(figure["script"][:-3].replace("/", "."))
        if hasattr(module, "main"):
            return module.main(extra)
        return figure_entrypoint(args.figure, extra)
    if args.list:
        if extra:
            parser.error("Unexpected arguments for --list")
        for f in load_registry()["figures"]:
            print(f"{f['id']:<32} {f['status']:<52} {f['script']}")
        return 0
    check = argparse.ArgumentParser(description="Public metadata/schema check")
    check.add_argument("--dataset", required=True)
    check_args = check.parse_args(extra)
    try:
        _, content, rows = load_public_metadata(check_args.dataset)
    except (ValueError, OSError) as exc:
        check.error(str(exc))
    print(json.dumps(metadata_summary(content, rows), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
