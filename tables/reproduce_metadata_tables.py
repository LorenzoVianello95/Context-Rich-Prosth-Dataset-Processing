#!/usr/bin/env python3
"""Generate count/coverage tables using only date-free public CSV metadata."""

import argparse
import csv
import json
import platform
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common.metadata import FAMILIES, digest, load_public_metadata


def compute_tables(rows):
    variants = defaultdict(set)
    for row in rows:
        if row["session_id"]:
            variants[(row["family"], row["configuration_code"] or "UNKNOWN")].add(row["session_id"])
    variant_rows = [{"family": f, "configuration_code": code, "source_sessions": len(sessions)}
                    for (f, code), sessions in sorted(variants.items(), key=lambda x: (FAMILIES.index(x[0][0]), -len(x[1]), x[0][1]))]
    coverage = []
    for family in FAMILIES:
        rr = [r for r in rows if r["family"] == family]
        accepted = [r for r in rr if r["status"] == "accepted"]
        known_duration = [float(r["verified_grid_duration_s"]) for r in accepted if r.get("verified_grid_duration_s")]
        coverage.append({"family": family, "source_recordings": len(rr),
                         "source_sessions": len({r["session_id"] for r in rr if r["session_id"]}),
                         "recordings_100hz": len(accepted), "native_recordings": len(rr)-len(accepted),
                         "rows_100hz": sum(int(r["rows"]) for r in accepted),
                         "native_rows": sum(int(r["rows"]) for r in rr if r["status"] == "timing_quarantine"),
                         "verified_logging_grid_hours": sum(known_duration)/3600,
                         "accepted_records_without_verified_duration": len(accepted)-len(known_duration)})
    participants = []
    for participant in sorted({r["participant_id"] for r in rows if r["participant_id"]}):
        rr = [r for r in rows if r["participant_id"] == participant]
        result = {"participant_id": participant}
        result.update({f+"_visit_groups": len({r["visit_id"] for r in rr if r["family"] == f and r["visit_id"]}) for f in FAMILIES})
        result.update(unique_visit_groups=len({r["visit_id"] for r in rr if r["visit_id"]}),
                      source_sessions=len({r["session_id"] for r in rr if r["session_id"]}),
                      families_used=len({r["family"] for r in rr}),
                      unknown_visit_records=sum(not r["visit_id"] for r in rr))
        participants.append(result)
    return variant_rows, coverage, participants


def write_csv(path, rows):
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def tex(value):
    return str(value).replace("\\", r"\textbackslash{}").replace("_", r"\_").replace("&", r"\&").replace("%", r"\%")


def write_tex(path, headers, rows, caption, label):
    lines = [r"\begin{table}[ht]", r"\centering", r"\scriptsize", r"\begin{tabular}{"+"l"*len(headers)+"}", r"\hline",
             " & ".join(map(tex, headers))+r" \\", r"\hline"]
    lines += [" & ".join(map(tex, row))+r" \\" for row in rows]
    lines += [r"\hline", r"\end{tabular}", r"\caption{"+caption+"}", r"\label{"+label+"}", r"\end{table}"]
    path.write_text("\n".join(lines)+"\n", encoding="utf-8")


def build(dataset, output):
    root, content, rows = load_public_metadata(dataset)
    output = Path(output).resolve()
    if output.is_relative_to(root) or root.is_relative_to(output):
        raise ValueError("Output must be separate from the dataset")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output is not empty; choose a new folder")
    variants, coverage, participants = compute_tables(rows)
    output.mkdir(parents=True, exist_ok=True)
    for name, values in (("device_session_counts", variants), ("release_coverage", coverage), ("participant_visit_counts", participants)):
        write_csv(output/(name+".csv"), values)
    write_tex(output/"device_session_counts.tex", ["Family", "Configuration", "Source folders"],
              [[r[k] for k in ("family", "configuration_code", "source_sessions")] for r in variants],
              "Distinct source-folder sessions by configuration, not unique visit days.", "tab:device-sessions-generated")
    write_tex(output/"release_coverage.tex", ["Family", "Recordings", "100 Hz", "Native", "Folders"],
              [[r[k] for k in ("family", "source_recordings", "recordings_100hz", "native_recordings", "source_sessions")] for r in coverage],
              "Coverage of verified-clock recordings and retained native-clock exceptions.", "tab:coverage-generated")
    write_tex(output/"participant_visit_counts.tex", ["Participant", *FAMILIES, "Unique visits", "Folders", "Unknown visits"],
              [[r["participant_id"], *[r[f+"_visit_groups"] for f in FAMILIES], r["unique_visit_groups"], r["source_sessions"], r["unknown_visit_records"]] for r in participants],
              "Complete participant visit counts. Family counts need not sum to unique visits when a visit spans families.", "tab:participant-visits-generated")
    top = sorted(participants, key=lambda r: (-r["unique_visit_groups"], r["participant_id"]))[:25]
    write_csv(output/"top_subjects_by_visit_days.csv", top)
    write_tex(output/"top_subjects_by_visit_days.tex", ["Participant", "Unique visits", "Families"],
              [[r["participant_id"], r["unique_visit_groups"], r["families_used"]] for r in top],
              "Most represented participants by observed visit groups. No calendar dates are used.", "tab:top-visits-generated")
    manifest = {"schema_version": 1, "python": platform.python_version(), "dataset_schema": content["schema_version"],
                "input_hashes": {name: digest(root/name) for name in ("metadata.csv", "DATASET_CONTENT.json")},
                "source_records": len(rows), "participants": len(participants),
                "source_sessions": len({r["session_id"] for r in rows if r["session_id"]}),
                "participant_visit_groups": len({r["visit_id"] for r in rows if r["visit_id"]}),
                "family_session_counts": {r["family"]: r["source_sessions"] for r in coverage},
                "unknown_participant_records": sum(not r["participant_id"] for r in rows),
                "unknown_visit_records": sum(not r["visit_id"] for r in rows),
                "all_figures_implemented": False,
                "scope": "Metadata-only count tables; not hardware/demographic tables, calendar figures or waveform analyses."}
    manifest["outputs"] = {p.name: digest(p) for p in sorted(output.iterdir()) if p.is_file()}
    (output/"execution_manifest.json").write_text(json.dumps(manifest, indent=2)+"\n", encoding="utf-8")
    print(json.dumps({k: manifest[k] for k in ("source_records", "participants", "source_sessions", "participant_visit_groups", "family_session_counts")}, indent=2))
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        build(args.dataset, args.output_dir)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
