#!/usr/bin/env python3
"""Four family pies of decoded-state time occupancy from public continuous CSV."""

import json
import platform
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.cli import figure_entrypoint
from common.metadata import FAMILIES, ROOT, digest


def render(summary, output, *, denominator="verified_time", min_percent=2.0, dpi=220):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Patch
    config = json.loads((ROOT/"configs/activities.json").read_text(encoding="utf-8"))
    categories = config["categories"]
    allowed = {c["key"] for c in categories}
    if allowed != set(summary["categories"]):
        raise ValueError("Activity color configuration and numerical categories differ")
    if denominator not in {"verified_time", "assigned_activity"}:
        raise ValueError("Unknown pie denominator")
    visible = categories if denominator == "verified_time" else categories[:9]
    used = {c["key"] for c in visible if any(summary["family_summary"][f]["milliseconds_by_category"][c["key"]] > 0 for f in FAMILIES)}
    with plt.rc_context({"font.family": "DejaVu Sans", "font.size": 12, "svg.fonttype": "none"}):
        fig, axes = plt.subplots(1, len(FAMILIES), figsize=(18, 6.1))
        for ax, family in zip(axes, FAMILIES):
            info = summary["family_summary"][family]
            slices = [c for c in visible if info["milliseconds_by_category"][c["key"]] > 0]
            values = [info["milliseconds_by_category"][c["key"]] for c in slices]
            total = sum(values)
            if total:
                labels = [c["key"] if value/total*100 >= min_percent else "" for c, value in zip(slices, values)]
                wedges, _, percents = ax.pie(values, labels=labels, startangle=90, counterclock=False,
                    colors=[c["color"] for c in slices], labeldistance=1.07, pctdistance=.70,
                    autopct=lambda pct: f"{pct:.1f}%" if pct >= min_percent else "",
                    textprops={"fontsize": 11}, wedgeprops={"linewidth": .8, "edgecolor": "white"})
                for wedge, text in zip(wedges, percents):
                    red, green, blue, _ = wedge.get_facecolor()
                    text.set_color("black" if .2126*red+.7152*green+.0722*blue > .55 else "white")
                    text.set_fontweight("bold")
            else:
                message = "No verified-clock time" if not info["verified_milliseconds"] else "No assigned activity time"
                ax.text(.5, .5, message, transform=ax.transAxes, ha="center", va="center")
                ax.set_axis_off()
            ax.set_title(family, fontsize=17, fontweight="bold", pad=18)
            ax.set_aspect("equal")
            ax.text(.5, -.10, f"{info['verified_recordings']:,} verified files | {info['verified_hours']:.2f} h\n"
                    f"Native-clock files excluded: {info['native_recordings_excluded']:,}",
                    transform=ax.transAxes, ha="center", va="top", fontsize=11)
        handles = [Patch(facecolor=c["color"], label=c["label"]) for c in visible if c["key"] in used]
        if handles:
            fig.legend(handles=handles, loc="lower center", ncol=5, frameon=False,
                       bbox_to_anchor=(.5, .055), fontsize=10.5, columnspacing=1.5)
        note = ("Percentages of all verified recording time; unknown labels are retained."
                if denominator == "verified_time" else
                "Percentages conditional on assigned 1X-9X time; unknown/outside time remains in the numerical report.")
        fig.text(.5, .012, note, ha="center", va="bottom", fontsize=10)
        fig.subplots_adjust(left=.025, right=.975, top=.87, bottom=.29, wspace=.20)
        paths = []
        for suffix in ("png", "svg"):
            path = Path(output)/f"activity_distribution.{suffix}"
            fig.savefig(path, dpi=dpi, bbox_inches="tight")
            paths.append(path)
        plt.close(fig)
    return paths


def configure(parser):
    parser.add_argument("--workers", type=int, default=4, help="Bounded worker processes for reading all accepted recording CSVs")
    parser.add_argument("--denominator", choices=("verified_time", "assigned_activity"), default="verified_time",
                        help="Default includes unknown/outside time in the pies; assigned_activity is conditional on 1X-9X only")
    parser.add_argument("--min-percent", type=float, default=2.0, help="Hide small slice text, not the slice or its reported values")
    parser.add_argument("--dpi", type=int, default=220)
    parser.add_argument("--no-render", action="store_true", help="Compute/export all numerical evidence without plotting")


def run(args):
    from common.activities import collect, export_numbers
    import numpy as np
    output, dataset = Path(args.output_dir).resolve(), Path(args.dataset).resolve()
    if output.is_relative_to(dataset) or dataset.is_relative_to(output):
        raise ValueError("Output must be separate from the dataset")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output is not empty; choose a new directory")
    if not 0 <= args.min_percent <= 100 or args.dpi < 1 or args.workers < 1:
        raise ValueError("Invalid percentage, dpi or worker count")
    # Fail before reading the full dataset if a required plotting library is absent.
    if not args.no_render:
        import matplotlib
    summary, records, states = collect(dataset, args.workers)
    output.mkdir(parents=True, exist_ok=True)
    export_numbers(output, summary, records, states, args.denominator)
    figures = [] if args.no_render else render(summary, output, denominator=args.denominator, min_percent=args.min_percent, dpi=args.dpi)
    manifest = {"schema_version": 1, "figure": "activity_distribution", "manuscript_label": "fig:pieActivity",
        "analysis_schema": summary["schema_version"], "input_hashes": summary["input_hashes"],
        "parameters": {"workers": args.workers, "denominator": args.denominator, "min_percent": args.min_percent, "dpi": args.dpi, "no_render": args.no_render},
        "verified_recordings_read_and_hashed": summary["verified_recordings"], "native_recordings_not_read": summary["native_recordings_excluded"],
        "verified_samples": summary["verified_samples"], "verified_milliseconds": summary["verified_milliseconds"],
        "all_recordings_accounted_for": len(records) == summary["verified_recordings"]+summary["native_recordings_excluded"],
        "runtime": {"python": platform.python_version(), "numpy": np.__version__, "matplotlib": None if args.no_render else matplotlib.__version__},
        "code_and_config_hashes": {name: digest(ROOT/name) for name in ("common/activities.py", "common/recordings.py", "common/metadata.py", "common/cli.py", "figures/fig_activity_distribution.py", "configs/activities.json", "figure_registry.json")},
        "figures": [p.name for p in figures],
        "outputs": {p.name: digest(p) for p in sorted(output.iterdir()) if p.is_file()},
        "dataset_modified": False, "manuscript_modified": False}
    (output/"execution_manifest.json").write_text(json.dumps(manifest, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    print(json.dumps({"figure": "activity_distribution", "verified_recordings": summary["verified_recordings"],
                      "native_recordings_excluded": summary["native_recordings_excluded"],
                      "verified_hours": summary["verified_milliseconds"]/3600000, "figures": manifest["figures"]}, indent=2))
    return manifest


def main(argv=None):
    return figure_entrypoint("activity_distribution", argv, runner=run, configure=configure)


if __name__ == "__main__":
    sys.exit(main())
