"""Read-only inputs, new output directories and portable execution manifests."""

import json
import platform
from importlib.metadata import PackageNotFoundError,version
from pathlib import Path

from .metadata import ROOT, digest


def new_output(dataset, output):
    dataset, output = Path(dataset).resolve(), Path(output).resolve()
    if output.is_relative_to(dataset) or dataset.is_relative_to(output):
        raise ValueError("Output must be separate from the dataset")
    if output.exists() and any(output.iterdir()):
        raise ValueError("Output is not empty; choose a new directory")
    output.mkdir(parents=True, exist_ok=True)
    return output


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False)+"\n", encoding="utf-8")


def manifest(output, figure, inputs, parameters=None, extra=None):
    runtime={}
    for name in ("numpy","scipy","matplotlib"):
        try:
            runtime[name]=version(name)
        except PackageNotFoundError:
            runtime[name]=None
    result = {"schema_version": 1, "figure": figure, "input_hashes": inputs,
              "parameters": parameters or {}, "python": platform.python_version(),
              "runtime":runtime,
              "config_hashes":{str(p.relative_to(ROOT)).replace("\\","/"):digest(p)
                               for p in [ROOT/"figure_registry.json",ROOT/"requirements.txt",*sorted((ROOT/"configs").glob("*.json"))]},
              "code_hashes": {str(p.relative_to(ROOT)).replace("\\", "/"): digest(p)
                              for p in sorted(ROOT.rglob("*.py"))
                              if not any(part in {"outputs", "__pycache__", ".venv"} for part in p.relative_to(ROOT).parts)},
              "outputs": {p.name: digest(p) for p in sorted(Path(output).iterdir()) if p.is_file()},
              "dataset_modified": False, "manuscript_modified": False}
    result.update(extra or {})
    write_json(Path(output)/"execution_manifest.json", result)
    return result
