"""Integer-millisecond occupancy of already decoded states, not event counts."""

import csv
import json
import time
from collections import Counter
from concurrent.futures import FIRST_COMPLETED, ProcessPoolExecutor, wait
from pathlib import Path

from .metadata import FAMILIES, ROOT, digest, load_public_metadata
from .recordings import public_checksums, read_named_columns, verified_time_support

KEYS = tuple(f"{d}X" for d in range(1, 10))+("unknown", "outside")


def category(state):
    if state < 0:
        return "unknown"
    return f"{state//10}X" if 10 <= state <= 99 else "outside"


def count_states(labels, final_ms):
    import numpy as np
    if len(labels) and not 1 <= final_ms <= 10:
        raise ValueError("Invalid final support interval")
    finite = np.isfinite(labels)
    if np.any(labels[finite] != np.rint(labels[finite])):
        raise ValueError("Nonintegral decoded state label; refusing implicit truncation")
    if np.any(labels[finite] < -32768) or np.any(labels[finite] > 32767):
        raise ValueError("Decoded labels exceed the declared int16 state schema")
    states = np.where(finite, labels, -1).astype(np.int64)
    samples = {key: 0 for key in KEYS}
    milliseconds = dict(samples)
    state_rows = []
    if not len(states):
        return samples, milliseconds, state_rows
    for state, count in zip(*np.unique(states, return_counts=True)):
        count = int(count)
        state = int(state)
        ms = count*10-(10-final_ms if states[-1] == state else 0)
        key = category(state)
        samples[key] += count
        milliseconds[key] += ms
        state_rows.append({"state": state, "category": key, "samples": count, "milliseconds": ms})
    return samples, milliseconds, state_rows


def inspect_record(root, row, expected_sha):
    values, actual_sha = read_named_columns(root, row, ("sample_index", "time_s", "state_labels"), expected_sha)
    total_ms, last_ms = verified_time_support(row, values[:, 0], values[:, 1])
    samples, ms, states = count_states(values[:, 2], last_ms)
    if sum(ms.values()) != total_ms or sum(samples.values()) != int(row["rows"]):
        raise ValueError("Activity occupancy does not reconcile with full recording time")
    return {"record_id": int(row["record_id"]), "family": row["family"], "status": "accepted",
            "rows": int(row["rows"]), "milliseconds": total_ms, "terminal_interval_ms": last_ms,
            "csv_path": row["csv_path"], "sha256": actual_sha, "hash_verified": True,
            "samples_by_category": samples, "milliseconds_by_category": ms, "states": states}


def collect(dataset, workers=4):
    root, content, rows = load_public_metadata(dataset)
    if workers < 1:
        raise ValueError("workers must be positive")
    expected = public_checksums(root)
    input_hashes = {name: digest(root/name) for name in ("metadata.csv", "DATASET_CONTENT.json", "checksums.sha256")}
    accepted = [r for r in rows if r["status"] == "accepted"]
    result = []
    todo = iter(accepted)
    started = last_log = time.monotonic()
    print(f"Activity occupancy: {len(accepted):,} verified recordings; {len(rows)-len(accepted):,} native records excluded from time", flush=True)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        pending = set()
        def submit():
            row = next(todo, None)
            if row is None:
                return False
            sha = expected.get(row["csv_path"])
            if not sha:
                raise ValueError("Recording absent from public checksum manifest")
            task = {k: row.get(k) for k in ("record_id", "family", "status", "rows", "csv_path", "duration_verified", "sampling_rate_hz", "verified_grid_duration_s")}
            pending.add(pool.submit(inspect_record, root, task, sha))
            return True
        for _ in range(workers*2):
            if not submit():
                break
        while pending:
            completed, pending = wait(pending, timeout=10, return_when=FIRST_COMPLETED)
            for future in completed:
                result.append(future.result())
                submit()
            if time.monotonic()-last_log >= 20 or not pending:
                print(f"{len(result):,}/{len(accepted):,} label streams checked; {time.monotonic()-started:.0f}s", flush=True)
                last_log = time.monotonic()
    if len(result) != len(accepted) or len({r["record_id"] for r in result}) != len(result):
        raise ValueError("Incomplete activity recording inventory")
    if any(digest(root/name) != sha for name, sha in input_hashes.items()):
        raise ValueError("Dataset metadata/index changed during analysis")
    families, state_totals = {}, Counter()
    for family in FAMILIES:
        rr = [r for r in result if r["family"] == family]
        native = [r for r in rows if r["family"] == family and r["status"] == "timing_quarantine"]
        counts = {key: sum(r["samples_by_category"][key] for r in rr) for key in KEYS}
        ms = {key: sum(r["milliseconds_by_category"][key] for r in rr) for key in KEYS}
        families[family] = {"verified_recordings": len(rr), "verified_samples": sum(r["rows"] for r in rr),
            "verified_milliseconds": sum(ms.values()), "verified_hours": sum(ms.values())/3600000,
            "assigned_milliseconds": sum(ms[k] for k in KEYS[:9]), "unknown_milliseconds": ms["unknown"],
            "outside_milliseconds": ms["outside"], "samples_by_category": counts, "milliseconds_by_category": ms,
            "native_recordings_excluded": len(native), "native_samples_not_converted_to_time": sum(int(r["rows"]) for r in native),
            "native_hours": None}
        for r in rr:
            for state in r["states"]:
                state_totals[(family, state["state"], state["category"], "samples")] += state["samples"]
                state_totals[(family, state["state"], state["category"], "milliseconds")] += state["milliseconds"]
    states = [{"family": f, "state": s, "category": c, "samples": state_totals[(f,s,c,"samples")],
               "milliseconds": state_totals[(f,s,c,"milliseconds")]} for f,s,c in sorted({(f,s,c) for f,s,c,_ in state_totals}, key=lambda v: (FAMILIES.index(v[0]), v[1]))]
    summary = {"schema_version": "activity_state_occupancy_1.0", "dataset_schema": content["schema_version"],
               "method": "Pooled decoded-state occupancy; every verified sample contributes a left-closed support bin. Integer milliseconds; terminal bin clipped to source-grid duration.",
               "categories": list(KEYS), "family_summary": families,
               "verified_recordings": len(result), "native_recordings_excluded": len(rows)-len(result),
               "verified_samples": sum(r["rows"] for r in result),
               "verified_milliseconds": sum(r["milliseconds"] for r in result),
               "ceil_output_samples_times_10ms": sum(r["rows"] for r in result)*10,
               "label_source": "state_labels from the public CSV, already decoded and held across sparse-event zero spans. No raw-event re-decoding or sensor-mask-based record removal.",
               "unknown_policy": "Negative or nonfinite state labels are unknown. Integral states outside 10..99 are outside target decades, including zero and raw transition-like values. Nonintegral labels fail validation.",
               "timing": "Only accepted duration-verified 100 Hz files from the verified 1 ms source grid. Native files retained in the audit, never assigned assumed hours.",
               "label_alignment": content.get("source_processing", {}).get("label_alignment", "Unverified/unspecified"),
               "weighting": "Time pooled across recordings within each family, not equal weighting of subjects, visits, cycles or events.",
               "input_hashes": input_hashes, "elapsed_s": time.monotonic()-started}
    for row in rows:
        if row["status"] == "timing_quarantine":
            result.append({"record_id": int(row["record_id"]), "family": row["family"], "status": row["status"],
                "rows": int(row["rows"]), "milliseconds": None, "terminal_interval_ms": None,
                "csv_path": row["csv_path"], "sha256": expected.get(row["csv_path"]), "hash_verified": False,
                "samples_by_category": {}, "milliseconds_by_category": {}, "states": []})
    return summary, sorted(result, key=lambda r: r["record_id"]), states


def write_csv(path, rows):
    if not rows:
        return
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def export_numbers(output, summary, records, states, denominator):
    output = Path(output)
    summary["plot_denominator"] = denominator
    (output/"activity_distribution.json").write_text(json.dumps(summary, indent=2, allow_nan=False)+"\n", encoding="utf-8")
    values = []
    for family, info in summary["family_summary"].items():
        for key in KEYS:
            ms = info["milliseconds_by_category"][key]
            values.append({"family": family, "category": key, "samples": info["samples_by_category"][key],
                "milliseconds": ms, "seconds": ms/1000, "hours": ms/3600000,
                "fraction_of_verified_time": ms/info["verified_milliseconds"] if info["verified_milliseconds"] else None,
                "fraction_of_assigned_time": ms/info["assigned_milliseconds"] if key in KEYS[:9] and info["assigned_milliseconds"] else None})
    write_csv(output/"activity_distribution_by_family.csv", values)
    write_csv(output/"state_occupancy_by_family.csv", states)
    audit = []
    for r in records:
        row = {k: r[k] for k in ("record_id", "family", "status", "rows", "milliseconds", "terminal_interval_ms", "csv_path", "sha256", "hash_verified")}
        row["exclusion_reason"] = "unverified_native_clock" if r["status"] != "accepted" else ""
        row.update({f"{key}_samples": r["samples_by_category"].get(key) for key in KEYS})
        row.update({f"{key}_milliseconds": r["milliseconds_by_category"].get(key) for key in KEYS})
        audit.append(row)
    write_csv(output/"recording_occupancy_audit.csv", audit)
    text = ["# Activity Distribution from Public CSV", "", "## Method", "",
            "This is time occupancy of already decoded state labels, not counts of sparse transition events. Each verified 100 Hz sample represents a support bin; the final bin is clipped to the verified source-grid duration. Integer milliseconds make unknown/assigned/outside totals reconcile exactly.", "",
            "The pie denominator is `"+denominator+"`. The default `verified_time` includes unknown labels and outside-decade states. `assigned_activity` shows conditional 1X-9X proportions only; exclusions remain in the numerical tables and audit. All nine activity colors remain fixed across families. Modes 8X/9X are not given unsupported semantic labels.", "",
            "Unknown means a negative or nonfinite decoded state. Nonnegative integral values outside 10..99, including zero, are outside target decades. Raw four/five-digit transition values are not reinterpreted as activities. State labels already incorporate held state across sparse-event zero spans. Neither sensor missingness nor a lack of accepted gait cycles removes activity time.", "",
            "Time is pooled across recordings, not averaged equally by participant/session. Labels retain the dataset's approximate annotation-to-DAQ association; this is not independent activity ground truth. Native-clock recordings are listed but not converted to hours or silently resampled.", "",
            "## Coverage", "", "| Family | Verified files | Verified hours | Assigned hours | Unknown hours | Outside hours | Native files excluded |",
            "|---|---:|---:|---:|---:|---:|---:|"]
    for family, info in summary["family_summary"].items():
        text.append(f"| {family} | {info['verified_recordings']:,} | {info['verified_hours']:.6f} | {info['assigned_milliseconds']/3600000:.6f} | {info['unknown_milliseconds']/3600000:.6f} | {info['outside_milliseconds']/3600000:.6f} | {info['native_recordings_excluded']:,} |")
    correction = (summary["ceil_output_samples_times_10ms"]-summary["verified_milliseconds"])/1000
    text += ["", f"Terminal-interval clipping removes **{correction:.3f} s** compared with assigning every ceil-resampled output row a full 0.01 s. This is support accounting, not deleting samples or modifying signals.", "",
             "## Reproduction", "", "The JSON/CSV summaries, per-record input hashes and audit are generated from all verified public recording files. Native-file hashes in the audit come from the dataset index and are explicitly not rechecked by this analysis. No original calendar dates, private paths, MAT files, legacy caches or source crosswalks are used. No dataset or manuscript was modified.", ""]
    (output/"activity_distribution.md").write_text("\n".join(text), encoding="utf-8")
