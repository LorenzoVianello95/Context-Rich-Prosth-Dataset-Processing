"""Standard-library public metadata loader; no private workspace dependencies."""

import csv
import hashlib
import json
import re
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
FAMILIES = ("Fox", "OSL", "HK", "VU")
SCHEMA = "multileg_relative_visit_csv_1.0"
PRIVATE_FIELDS = {"subject", "session", "recording_date", "source_path", "source_sha256"}
REQUIRED = {"record_id", "participant_id", "session_id", "visit_id", "visit_number", "elapsed_visit_days",
            "family", "configuration_code", "status", "rows", "csv_path", "current_csv_path", "annotation_csv_path"}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def relative_path(relative):
    """Cheap lexical check for metadata; does not touch every data file."""
    posix = PurePosixPath(relative)
    if not relative or "\\" in relative or ":" in relative or posix.is_absolute() or ".." in posix.parts:
        raise ValueError("Expected a relative public dataset path")
    return posix


def dataset_path(root, relative):
    """Use on actual file access; resolving also rejects escaping symlinks."""
    relative_path(relative)
    root = Path(root).resolve()
    result = (root/relative).resolve()
    if not result.is_relative_to(root) or result == root:
        raise ValueError("Dataset path escapes its root")
    return result


def load_registry():
    registry = json.loads((ROOT/"figure_registry.json").read_text(encoding="utf-8"))
    figures = registry["figures"]
    for key in ("id", "script", "manuscript_label"):
        if len({f[key] for f in figures}) != len(figures):
            raise ValueError("Duplicate figure " + key)
    return registry


def load_public_metadata(dataset):
    root = Path(dataset).resolve()
    content = json.loads((root/"DATASET_CONTENT.json").read_text(encoding="utf-8"))
    if content.get("schema_version") != SCHEMA:
        raise ValueError("Expected the relative-visit public CSV schema; private/legacy exports are not supported")
    with (root/"metadata.csv").open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        fields = set(reader.fieldnames or [])
        if fields & PRIVATE_FIELDS:
            raise ValueError("Private date/path metadata columns are not accepted")
        if not REQUIRED.issubset(fields):
            raise ValueError("Missing public metadata columns: " + ", ".join(sorted(REQUIRED-fields)))
        rows = list(reader)
    ids, visit_groups = set(), {}
    for row in rows:
        rid = int(row["record_id"])
        if rid in ids or int(row["rows"]) < 0:
            raise ValueError("Duplicate record ID or invalid row count")
        ids.add(rid)
        if row["family"] not in FAMILIES or row["status"] not in {"accepted", "timing_quarantine"}:
            raise ValueError("Unknown family or clock status")
        for key, pattern in (("participant_id", r"TF\d{2,3}"), ("session_id", r"S\d{4}"), ("visit_id", r"V\d{4}")):
            if row[key] and not re.fullmatch(pattern, row[key]):
                raise ValueError("Unexpected public identifier format")
        for key in ("csv_path", "current_csv_path", "annotation_csv_path"):
            if row[key]:
                relative_path(row[key])
        if row["visit_id"]:
            if not row["participant_id"] or int(row["visit_number"]) < 1 or int(row["elapsed_visit_days"]) < 0:
                raise ValueError("Known visit needs participant and valid relative timing")
            group = (row["participant_id"], row["visit_number"], row["elapsed_visit_days"])
            if visit_groups.setdefault(row["visit_id"], group) != group:
                raise ValueError("Inconsistent shared visit")
        elif row["visit_number"] or row["elapsed_visit_days"]:
            raise ValueError("Unknown visit cannot have fabricated relative timing")
    if len(rows) != content.get("records"):
        raise ValueError("Metadata and content-summary recording counts differ")
    return root, content, rows


def metadata_summary(content, rows):
    return {"dataset_schema": content["schema_version"], "records": len(rows),
            "participants": len({r["participant_id"] for r in rows if r["participant_id"]}),
            "source_sessions": len({r["session_id"] for r in rows if r["session_id"]}),
            "shared_visits": len({r["visit_id"] for r in rows if r["visit_id"]}),
            "recordings_100hz": sum(r["status"] == "accepted" for r in rows),
            "native_recordings": sum(r["status"] == "timing_quarantine" for r in rows),
            "scope": "Metadata/schema check only, not waveform integrity, segmentation, physical calibration or privacy clearance."}
