"""Decoded occupancy, exact terminal support, native exclusion and rendering."""

import csv
import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from common.activities import collect, count_states, inspect_record
from common.metadata import SCHEMA
from common.recordings import verified_time_support
from figures.fig_activity_distribution import render, run

try:
    import numpy as np
except ImportError:
    np = None


def fixture(root):
    root.mkdir()
    cases = (("Fox", [21,21,21,22,-1], .043), ("OSL", [11,31,41], .025),
             ("HK", [70,74,99,2122], .040), ("VU", [-1,-1], .011))
    rows, hashes = [], {}
    for rid, (family, labels, duration) in enumerate(cases):
        path = f"recordings/{family}/{rid:06d}.csv"
        target = root/path
        target.parent.mkdir(parents=True)
        with target.open("w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, lineterminator="\n")
            writer.writerow(["sample_index", "time_s", "Fz", "Fz_valid", "state_labels"])
            writer.writerows((i, i/100, 0, 0, label) for i,label in enumerate(labels))
        hashes[path] = hashlib.sha256(target.read_bytes()).hexdigest()
        rows.append({"record_id": str(rid), "participant_id": "TF98", "session_id": f"S{rid+1:04d}",
                     "visit_id": "V0001", "visit_number": "1", "elapsed_visit_days": "0", "family": family,
                     "configuration_code": "synthetic", "status": "accepted", "rows": str(len(labels)),
                     "sampling_rate_hz": "100", "duration_verified": "1", "verified_grid_duration_s": str(duration),
                     "csv_path": path, "annotation_csv_path": "", "current_csv_path": f"currents/{family}/{rid:06d}.csv"})
    native = dict(rows[-1])
    native.update(record_id="4", session_id="S0005", status="timing_quarantine", rows="999", sampling_rate_hz="",
                  duration_verified="0", verified_grid_duration_s="", csv_path="timing_quarantine/VU/000004.csv.gz")
    rows.append(native)
    # Intentionally absent native payload: the activity analysis must not read it.
    hashes[native["csv_path"]] = hashlib.sha256(b"unread native data").hexdigest()
    with (root/"metadata.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    (root/"DATASET_CONTENT.json").write_text(json.dumps({"schema_version": SCHEMA, "records": len(rows),
                                                       "source_processing": {"label_alignment": "synthetic"}}))
    for name in ("metadata.csv", "DATASET_CONTENT.json"):
        hashes[name] = hashlib.sha256((root/name).read_bytes()).hexdigest()
    (root/"checksums.sha256").write_text("".join(f"{sha}  {path}\n" for path,sha in hashes.items()))
    return rows, hashes


@unittest.skipIf(np is None, "NumPy is required for activity analysis tests")
class ActivityTests(unittest.TestCase):
    def test_dense_repeated_states_count_all_samples_not_events(self):
        samples, ms, _ = count_states(np.array([21,21,21,22,22]), 10)
        self.assertEqual(samples["2X"], 5)
        self.assertEqual(ms["2X"], 50)

    def test_terminal_support_is_clipped_exactly_in_integer_milliseconds(self):
        row = {"status": "accepted", "duration_verified": "1", "sampling_rate_hz": "100", "rows": "2", "verified_grid_duration_s": ".013"}
        total, final = verified_time_support(row, np.arange(2), np.arange(2)/100)
        self.assertEqual((total, final), (13, 3))
        samples, ms, _ = count_states(np.array([21, -1]), final)
        self.assertEqual(ms["2X"], 10)
        self.assertEqual(ms["unknown"], 3)
        self.assertEqual(sum(samples.values()), 2)
        row.update(rows="1", verified_grid_duration_s=".002")
        self.assertEqual(verified_time_support(row, np.array([0]), np.array([0.])), (2, 2))

    def test_unknown_outside_and_passive_states_not_silently_dropped(self):
        samples, ms, _ = count_states(np.array([-32768,-1,np.nan,np.inf,0,9,100,2122,70,74,99]), 10)
        self.assertEqual(samples["unknown"], 4)
        self.assertEqual(samples["outside"], 4)
        self.assertEqual(samples["7X"], 2)
        self.assertEqual(samples["9X"], 1)
        self.assertEqual(samples["2X"], 0)  # 2122 is not a decoded state.
        self.assertEqual(sum(ms.values()), 110)
        with self.assertRaisesRegex(ValueError, "Nonintegral"):
            count_states(np.array([21.5]), 10)

    def test_bad_grid_duration_and_native_rate_refused(self):
        row = {"status": "accepted", "duration_verified": "1", "sampling_rate_hz": "100", "rows": "2", "verified_grid_duration_s": ".013"}
        with self.assertRaisesRegex(ValueError, "100 Hz grid"):
            verified_time_support(row, np.array([0,1]), np.array([0,.02]))
        row["verified_grid_duration_s"] = ".03"
        with self.assertRaisesRegex(ValueError, "row count"):
            verified_time_support(row, np.array([0,1]), np.array([0,.01]))
        row["status"] = "timing_quarantine"
        with self.assertRaisesRegex(ValueError, "verified-clock"):
            verified_time_support(row, np.array([0,1]), np.array([0,.01]))

    def test_all_records_reconcile_and_native_samples_never_get_hours(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/"data"
            fixture(root)
            summary, records, _ = collect(root, workers=1)
            self.assertEqual(summary["verified_milliseconds"], 119)
            self.assertEqual(summary["verified_samples"], 14)
            self.assertEqual(len(records), 5)
            self.assertEqual(summary["family_summary"]["Fox"]["milliseconds_by_category"]["unknown"], 3)
            self.assertEqual(summary["family_summary"]["VU"]["unknown_milliseconds"], 11)
            self.assertIsNone(summary["family_summary"]["VU"]["native_hours"])
            self.assertFalse(records[-1]["hash_verified"])

    def test_checksum_change_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/"data"
            rows, hashes = fixture(root)
            (root/rows[0]["csv_path"]).write_text("changed")
            with self.assertRaisesRegex(ValueError, "checksum"):
                inspect_record(root, rows[0], hashes[rows[0]["csv_path"]])

    @unittest.skipUnless(importlib.util.find_spec("matplotlib"), "Matplotlib required")
    def test_render_and_counts_are_nonempty_and_input_data_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root/"data")
            before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/"data").rglob("*") if p.is_file()}
            args = SimpleNamespace(dataset=root/"data", output_dir=root/"out", workers=1, denominator="verified_time",
                                   min_percent=2, dpi=80, no_render=False)
            manifest = run(args)
            self.assertEqual(manifest["verified_milliseconds"], 119)
            self.assertGreater((root/"out/activity_distribution.png").stat().st_size, 1000)
            self.assertIn("<svg", (root/"out/activity_distribution.svg").read_text())
            self.assertEqual(before, {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in before})
            with self.assertRaisesRegex(ValueError, "not empty"):
                run(args)
            # Conditional normalization must also handle a family with no assigned time.
            summary = json.loads((root/"out/activity_distribution.json").read_text())
            (root/"conditional").mkdir()
            render(summary, root/"conditional", denominator="assigned_activity", dpi=60)

    def test_isolated_copy_dispatches_the_implemented_renderer_without_parent_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clone = root/"code"
            shutil.copytree(ROOT, clone, ignore=shutil.ignore_patterns("outputs", "__pycache__", "data", ".git"))
            fixture(root/"data")
            result = subprocess.run([sys.executable, "-B", "-I", str(clone/"reproduce.py"), "--figure", "activity_distribution",
                "--dataset", str(root/"data"), "--output-dir", str(root/"out"), "--workers", "1", "--no-render"],
                cwd=root, capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads((root/"out/activity_distribution.json").read_text())["verified_milliseconds"], 119)


if __name__ == "__main__":
    unittest.main()
