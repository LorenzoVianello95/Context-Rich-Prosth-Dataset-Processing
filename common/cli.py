"""Honest entry-point contract while the individual CSV renderers are ported."""

import argparse
import json

from .metadata import load_public_metadata, load_registry, metadata_summary


def figure_entrypoint(figure_id, argv=None, *, runner=None, configure=None):
    figures = {f["id"]: f for f in load_registry()["figures"]}
    figure = figures[figure_id]
    parser = argparse.ArgumentParser(description=figure["title"]+" ("+figure["manuscript_label"]+")")
    parser.add_argument("--dataset", help="External public CSV dataset root; never a private raw-data folder")
    parser.add_argument("--output-dir", help="New renderer output directory; existing outputs must not be overwritten")
    parser.add_argument("--status", action="store_true", help="Show the implementation status and missing prerequisites")
    parser.add_argument("--check-inputs", action="store_true", help="Check the public metadata/schema contract, not cycle or waveform validity")
    if configure is not None:
        configure(parser)
    args = parser.parse_args(argv)
    if args.status:
        print(json.dumps(figure, indent=2))
        return 0
    if args.check_inputs:
        if not figure["uses_public_csv"]:
            parser.error(figure["next_action"]+" Required inputs: "+", ".join(figure["required_inputs"]))
        if not args.dataset:
            parser.error("--dataset is required for an input-contract check")
        try:
            _, content, rows = load_public_metadata(args.dataset)
        except (ValueError, OSError) as exc:
            parser.error(str(exc))
        report = metadata_summary(content, rows)
        report.update(figure=figure_id, renderer_implemented=figure["renderer_implemented"], status=figure["status"], next_action=figure["next_action"])
        print(json.dumps(report, indent=2))
        return 0
    if runner is None or not figure["renderer_implemented"]:
        parser.error("CSV renderer is not implemented yet ("+figure["status"]+"). "+figure["next_action"]+" Use --status or --check-inputs. No figure was generated.")
    if not args.dataset or not args.output_dir:
        parser.error("--dataset and --output-dir are required for rendering")
    try:
        runner(args)
    except (ValueError, OSError, ImportError) as exc:
        parser.error(str(exc))
    return 0
