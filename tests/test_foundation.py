"""Portable contracts, real entry-point wiring and metadata-table regressions."""

import csv
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from common.metadata import SCHEMA, dataset_path, load_public_metadata, load_registry
from tables.reproduce_metadata_tables import build, compute_tables


def fixture(root):
    root.mkdir()
    rows = []
    for i, (family, session, visit) in enumerate((("HK", "S0001", "V0001"), ("HK", "S0001", "V0001"), ("Fox", "S0002", "V0001"))):
        rows.append({"record_id": str(i), "participant_id": "TF98", "session_id": session, "visit_id": visit,
                     "visit_number": "1", "elapsed_visit_days": "0", "family": family, "configuration_code": "example",
                     "status": "accepted", "rows": "100", "verified_grid_duration_s": "1",
                     "csv_path": f"recordings/{family}/{i:06d}.csv", "current_csv_path": f"currents/{family}/{i:06d}.csv",
                     "annotation_csv_path": f"annotations/{family}/{i:06d}_pvd.csv.gz"})
    with (root/"metadata.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    (root/"DATASET_CONTENT.json").write_text(json.dumps({"schema_version": SCHEMA, "records": len(rows)}))
    return rows


class FoundationTests(unittest.TestCase):
    def run_script(self, path, *args, cwd=None):
        return subprocess.run([sys.executable, "-B", "-I", str(path), *map(str, args)], cwd=cwd,
                              capture_output=True, text=True, timeout=30)

    def test_registry_has_one_script_per_manuscript_figure(self):
        figures = load_registry()["figures"]
        self.assertEqual(len(figures), 12)
        self.assertEqual(len({f["script"] for f in figures}), 12)
        for figure in figures:
            self.assertTrue((ROOT/figure["script"]).is_file())
            self.assertIn(f'figure_entrypoint("{figure["id"]}"', (ROOT/figure["script"]).read_text())

    def test_all_data_figures_have_explicit_legacy_source_provenance(self):
        figures=load_registry()["figures"]
        self.assertEqual(sum(f["renderer_implemented"] for f in figures),10)
        for figure in figures:
            if not figure["renderer_implemented"]:
                self.assertEqual(figure["status"],"excluded_by_owner_non_data_image")
                continue
            self.assertTrue(figure["legacy_sources"])
            for source in figure["legacy_sources"]:
                self.assertTrue(source["script"].startswith("explore_multiple_datasets/"))
                self.assertEqual(len(source["sha256_at_port"]),64)

    def test_every_entrypoint_help_and_status_work_without_data(self):
        for figure in load_registry()["figures"]:
            with self.subTest(figure=figure["id"]):
                result = self.run_script(ROOT/figure["script"], "--help")
                self.assertEqual(result.returncode, 0, result.stderr)
                result = self.run_script(ROOT/figure["script"], "--status")
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(json.loads(result.stdout)["id"], figure["id"])

    def test_pending_renderer_fails_without_writing_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/"not_created"
            result = self.run_script(ROOT/"figures/fig_dataset_overview.py", "--output-dir", output)
            self.assertEqual(result.returncode, 2)
            self.assertIn("not implemented", result.stderr)
            self.assertFalse(output.exists())

    def test_public_metadata_and_count_definitions(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = fixture(Path(tmp)/"data")
            _, _, loaded = load_public_metadata(Path(tmp)/"data")
            self.assertEqual(loaded, rows)
            variants, coverage, participants = compute_tables(loaded)
            self.assertEqual(sum(r["source_sessions"] for r in variants), 2)
            self.assertEqual(participants[0]["unique_visit_groups"], 1)
            self.assertEqual(participants[0]["HK_visit_groups"], 1)
            self.assertEqual(participants[0]["Fox_visit_groups"], 1)
            self.assertEqual(sum(r["rows_100hz"] for r in coverage), 300)

    def test_rejects_private_schema_and_private_fields(self):
        with tempfile.TemporaryDirectory() as tmp:
            data = Path(tmp)/"data"
            fixture(data)
            path = data/"DATASET_CONTENT.json"
            path.write_text(json.dumps({"schema_version": "private_legacy", "records": 3}))
            with self.assertRaisesRegex(ValueError, "private/legacy"):
                load_public_metadata(data)
            path.write_text(json.dumps({"schema_version": SCHEMA, "records": 3}))
            text = (data/"metadata.csv").read_text()
            lines = text.splitlines()
            lines[0] += ",recording_date"
            (data/"metadata.csv").write_text("\n".join(lines)+"\n")
            with self.assertRaisesRegex(ValueError, "Private"):
                load_public_metadata(data)

    def test_paths_cannot_escape_dataset(self):
        with tempfile.TemporaryDirectory() as tmp:
            for relative in ("../outside", "/outside", "C:/outside", "..\\outside"):
                with self.subTest(relative=relative), self.assertRaises(ValueError):
                    dataset_path(tmp, relative)

    def test_table_build_is_read_only_and_refuses_overwrites(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture(root/"data")
            before = (root/"data/metadata.csv").read_bytes()
            report = build(root/"data", root/"out")
            self.assertEqual(report["participant_visit_groups"], 1)
            self.assertTrue((root/"out/participant_visit_counts.tex").is_file())
            self.assertTrue((root/"out/top_subjects_by_visit_days.tex").is_file())
            self.assertEqual(before, (root/"data/metadata.csv").read_bytes())
            with self.assertRaisesRegex(ValueError, "not empty"):
                build(root/"data", root/"out")
            with self.assertRaisesRegex(ValueError, "separate"):
                build(root/"data", root/"data/out")

    def test_unknown_visits_are_not_invented_and_native_hours_not_assumed(self):
        with tempfile.TemporaryDirectory() as tmp:
            rows = fixture(Path(tmp)/"data")
            for row in rows:
                row.update(visit_id="", visit_number="", elapsed_visit_days="", status="timing_quarantine")
            _, coverage, participants = compute_tables(rows)
            self.assertEqual(participants[0]["unique_visit_groups"], 0)
            self.assertEqual(participants[0]["unknown_visit_records"], 3)
            self.assertEqual(sum(r["verified_logging_grid_hours"] for r in coverage), 0)

    def test_standalone_copy_and_cli_need_no_parent_workspace(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            clone = root/"standalone"
            shutil.copytree(ROOT, clone, ignore=shutil.ignore_patterns("__pycache__", "outputs", "data", ".git"))
            fixture(root/"dataset")
            result = self.run_script(clone/"reproduce.py", "--list", cwd=root)
            self.assertEqual(result.returncode, 0, result.stderr)
            result = self.run_script(clone/"figures/fig_gait_sensor_grid.py", "--dataset", root/"dataset", "--check-inputs", cwd=root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(json.loads(result.stdout)["renderer_implemented"])
            result = self.run_script(clone/"tables/reproduce_metadata_tables.py", "--dataset", root/"dataset", "--output-dir", root/"tables", cwd=root)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["source_records"], 3)


if __name__ == "__main__":
    unittest.main()
