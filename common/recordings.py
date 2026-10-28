"""Named-column reads with public checksums and verified 100 Hz support bins."""

import csv
import hashlib
import io
import math

from .metadata import dataset_path, digest


def public_checksums(root):
    expected = {}
    path = root/"checksums.sha256"
    with path.open(encoding="utf-8") as f:
        for line in f:
            sha, relative = line.rstrip("\n").split("  ", 1)
            if relative in expected:
                raise ValueError("Duplicate dataset checksum entry")
            expected[relative] = sha
    for name in ("metadata.csv", "DATASET_CONTENT.json"):
        if expected.get(name) != digest(root/name):
            raise ValueError("Public dataset metadata/content checksum mismatch")
    return expected


def read_named_columns(root, row, names, expected_sha256):
    """Read one verified recording once; hash the same bytes that are parsed."""
    import numpy as np
    path = dataset_path(root, row["csv_path"])
    if path.stat().st_size > 512*1024**2:
        raise ValueError("Recording exceeds the bounded 512 MiB CSV reader; use a chunked reader")
    raw = path.read_bytes()
    actual_sha = hashlib.sha256(raw).hexdigest()
    if actual_sha != expected_sha256:
        raise ValueError("Recording checksum mismatch for public record " + str(row["record_id"]))
    stream = io.BytesIO(raw)
    header = next(csv.reader([stream.readline().decode("utf-8").strip()]))
    if len(header) != len(set(header)) or not set(names).issubset(header):
        raise ValueError("Missing or duplicate recording columns")
    n = int(row["rows"])
    if n == 0:
        if stream.read().strip():
            raise ValueError("Empty metadata record has data rows")
        return np.empty((0, len(names)), dtype=np.float64), actual_sha
    data = np.loadtxt(stream, delimiter=",", usecols=tuple(header.index(name) for name in names),
                      dtype=np.float64, ndmin=2)
    if data.shape != (n, len(names)):
        raise ValueError("Recording row count differs from metadata")
    return data, actual_sha


def verified_time_support(row, sample_index, time_s):
    """Return exact source-grid milliseconds and final-bin weight, not N/100."""
    import numpy as np
    if row["status"] != "accepted" or row.get("duration_verified") != "1" or float(row.get("sampling_rate_hz", 0)) != 100:
        raise ValueError("Only verified-clock 100 Hz recordings can contribute occupancy time")
    n = int(row["rows"])
    if len(sample_index) != n or not np.array_equal(sample_index, np.arange(n, dtype=np.float64)):
        raise ValueError("Nonconsecutive sample_index")
    if not np.array_equal(time_s, np.arange(n, dtype=np.float64)/100):
        raise ValueError("Recording does not match its declared relative 100 Hz grid")
    duration = float(row["verified_grid_duration_s"])
    if not math.isfinite(duration) or duration < 0:
        raise ValueError("Invalid verified duration")
    milliseconds = round(duration*1000)
    if not math.isclose(duration, milliseconds/1000, rel_tol=0, abs_tol=1e-9):
        raise ValueError("Verified duration is not on the source 1 ms grid")
    if n != (milliseconds+9)//10:
        raise ValueError("Duration and ceil-resampled row count do not agree")
    last_ms = milliseconds-10*(n-1) if n else 0
    if n and not 1 <= last_ms <= 10:
        raise ValueError("Invalid terminal support interval")
    return milliseconds, last_ms
