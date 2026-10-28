# Multi-Leg Dataset: Figure and Table Reproduction

Standalone Python code for the data-driven manuscript figures and tables.
Use the public continuous CSV dataset as an **external input**. No imports from
the parent project, raw MAT archive, historical pickle datasets or manuscript
are required. This repository contains code, tests, configuration and methodology
only; datasets, generated figures, cached analyses and private inputs are excluded.

## Status

- All **ten data-driven figure entry points** are implemented and have produced
  PNG/SVG outputs on the full publication-format candidate.
- Eight figures use public metadata/CSV directly or a shared verified analysis.
  Two calendar renderers accept separately supplied aggregate inputs. Calendar
  inputs are **not included**; unapproved inputs remain review-only and are
  refused unless local review is explicitly enabled.
- The overview diagram and clinical-document illustration are excluded by owner
  request. Curated hardware and demographic tables are unchanged for now.
- Device/session, participant visit/device and continuous-dataset structure tables
  are implemented as separate scripts, with CSV/LaTeX output.
- No four-family common participant has three consecutive eligible labeled 2X
  cycles in the current release. Representative traces therefore require an
  explicit mixed-participant alternative; they are not claimed to reproduce the
  historical same-participant attempt.

The registry records the exact manuscript labels, legacy source filenames/hashes,
implementation status and limitations. Existing manuscript assets are untouched.
These are scientific/layout ports, not promises of pixel-identical figures or
unchanged results after cleaning/masking the released data.

## Figure Index

| Manuscript Label | Entry Script | Status |
|---|---|---|
| `fig:relationships` | `figures/fig_dataset_overview.py` | Excluded by owner (non-data image) |
| `fig:historyLegs` | `figures/fig_device_usage_over_time.py` | Separate calendar aggregates; review-only inputs |
| `fig:user_to_time_leg` | `figures/fig_subject_timeline.py` | Implemented |
| `fig:montlyActivity` | `figures/fig_activity_over_time.py` | Separate calendar aggregates; review-only inputs |
| `fig:pieActivity` | `figures/fig_activity_distribution.py` | Implemented |
| `fig:docai_fig` | `figures/fig_document_annotation_example.py` | Excluded by owner (non-data image) |
| `fig:SM_params_across_activity` | `figures/fig_controller_parameters.py` | Implemented |
| `fig:current_all_legs_activities` | `figures/fig_currents_by_activity.py` | Implemented |
| `fig:timedData` | `figures/fig_representative_sensor_traces.py` | Implemented; mixed-participant alternative |
| `fig:StepCountForLeg` | `figures/fig_step_counts.py` | Implemented |
| `fig:GaitSensors` | `figures/fig_gait_sensor_grid.py` | Implemented |
| `fig:amplitudeAndMean` | `figures/fig_sensor_amplitude.py` | Implemented |

## Install and Run

Tested with Python 3.12. Install the pinned dependencies in the interpreter used
for plotting. Metadata tables, CLI help/status and foundation tests use the
standard library; numerical figures additionally use NumPy, Matplotlib and SciPy.
Run these examples from **inside this code folder**. Dataset/output locations
can be absolute paths and need not be in the code repository. Replace `DATASET`
with the path to your downloaded public continuous CSV dataset.

```powershell
python -m pip install -r requirements.txt
python reproduce.py --list
python reproduce.py --check-dataset --dataset DATASET
python -m unittest discover -s tests -v
```

Build the shared cycle/parameter analysis once. All cycle-based figures use this
same versioned inventory; the build reads and checksums every accepted sensor
and current CSV and never writes to the dataset.

```powershell
python -m common.cycles --dataset DATASET --output-dir outputs/shared_analysis --workers 4
python reproduce.py --figure gait_sensor_grid --dataset DATASET --analysis-dir outputs/shared_analysis --output-dir outputs/gait_sensor_grid
python reproduce.py --figure currents_by_activity --dataset DATASET --analysis-dir outputs/shared_analysis --output-dir outputs/currents_by_activity
python reproduce.py --figure controller_parameters --dataset DATASET --analysis-dir outputs/shared_analysis --output-dir outputs/controller_parameters
python reproduce.py --figure step_counts --dataset DATASET --analysis-dir outputs/shared_analysis --output-dir outputs/step_counts
python reproduce.py --figure sensor_amplitude --dataset DATASET --analysis-dir outputs/shared_analysis --output-dir outputs/sensor_amplitude
```

Representative traces fail rather than silently mixing participants. To generate
the explicitly labeled alternative available for this candidate:

```powershell
python reproduce.py --figure representative_sensor_traces --dataset DATASET --analysis-dir outputs/shared_analysis --allow-mixed-participants --output-dir outputs/representative_sensor_traces
```

Activity occupancy reads dense decoded states, not sparse transition counts.
Its default denominator includes unknown time; the participant timeline uses
relative visit days, not reconstructed calendar dates.

```powershell
python reproduce.py --figure activity_distribution --dataset DATASET --output-dir outputs/activity_distribution --workers 4
python reproduce.py --figure subject_timeline --dataset DATASET --output-dir outputs/subject_timeline
```

### Calendar Inputs

The calendar renderers consume `monthly_device_usage.csv`,
`quarterly_activity.csv` and `calendar_review.json` from a **separate** directory.
They never open a linked-date crosswalk. Exact schemas and hash/reconciliation
checks are in `common/calendar_figures.py`. Unapproved inputs are refused unless
`--allow-review-only` explicitly enables a local review rendering. That flag does
not approve publication or make those aggregate inputs part of the public package.

```powershell
python reproduce.py --figure device_usage_over_time --dataset DATASET --aggregates-dir REVIEWED_AGGREGATES --allow-review-only --output-dir outputs/device_usage_review
python reproduce.py --figure activity_over_time --dataset DATASET --aggregates-dir REVIEWED_AGGREGATES --allow-review-only --output-dir outputs/activity_over_time_review
```

### Tables

```powershell
python tables/tab_device_sessions.py --dataset DATASET --output-dir outputs/table_device_sessions
python tables/tab_participant_visits.py --dataset DATASET --output-dir outputs/table_participant_visits
python tables/tab_dataset_structure.py --dataset DATASET --output-dir outputs/table_dataset_structure
python tables/reproduce_metadata_tables.py --dataset DATASET --output-dir outputs/metadata_tables
```

`tab_device_sessions.py` writes the thin four-family table with per-family totals
and a grand total. Calendar years are omitted from metadata-only output; they
require the separate approved aggregate policy. `tab_participant_visits.py`
exports a reduced top-25 table **and** full participant counts plus visits by
family. Source-folder sessions and visit groups are different counting units.
`tab_dataset_structure.py` describes the current continuous CSV schema, not v16
sliding windows. It intentionally uses a new table label for that structure.

### Batch Run

Use a **new** output directory. The batch reports generated, failed, excluded and
missing-input artifacts explicitly; it does not claim skipped figures succeeded.
An existing shared analysis can be reused with `--analysis-dir`.

```powershell
python reproduce_all.py --dataset DATASET --output-dir outputs/full_run --allow-mixed-participants --workers 4
```

Without `--aggregates-dir`, the two calendar figures are recorded as missing
aggregate inputs. To include local calendar review, additionally provide
`--aggregates-dir REVIEWED_AGGREGATES --allow-review-only`.

## Methods and Important Limits

See [methods and limitations](docs/methods_and_limits.md) and the
[activity occupancy specification](docs/activity_distribution.md).

- All accepted recordings are scanned; no file/session cap. The representative
  visualization alone uses a disclosed deterministic recording shortlist.
- Native-clock exceptions remain inventoried but are not assigned guessed hours
  or inserted into the 100 Hz analysis.
- Current signs and channel mappings are already applied in the release. Never
  invert again. Unverified/missing channels remain missing, not measured zeros.
- No physical calibration is supplied. Axis labels use uncalibrated source units.
- Every cycle-based output consumes one shared inventory. Retained edge fragments
  and endpoint/fallback rules are logged: these are accepted gait segments, not
  independently validated heel-strike counts.
- Four reviewed Fz exceptions are ported with approximate time-based row-ratio
  conversion. No hidden rerun of correlation-based channel assignment occurs.
- Full-cycle normalization occurs once. Signal eligibility requires the entire
  segment to be valid. All-zero ankle-current exclusions do not remove knees.
- Sensor/current curves are mean-only; family axes have different ranges, shared
  across columns with a common zero. Parameter error bars describe state-run
  means, and correlations of very few states require caution.
- Every generated analysis/figure/table has a numerical ledger and/or source data
  plus execution hashes. Outputs are refused if a directory is nonempty or inside
  the dataset. Generated files, datasets and private inputs are Git-ignored.
- No institutional privacy/consent or scientific calibration clearance is implied.

## Layout

```text
reproduce.py / reproduce_all.py       discovery, single-figure and batch entry points
figure_registry.json                 manuscript labels, provenance and status
figures/                             one script per manuscript figure
common/cycles.py                     full-data shared cycle/parameter analysis
common/cycle_figures.py               common numerical figure renderers
common/calendar_figures.py            aggregate-only calendar inputs/rendering
common/activities.py                  exact-support decoded-state occupancy
common/recordings.py / metadata.py    public schema, paths, checksums and grids
configs/                             palettes and legacy source snapshots
tables/                              per-table entry points and shared exporters
tests/                               self-contained synthetic regression tests
outputs/                             created at runtime; never tracked
```

## Publication Checklist

- Run the tests in a clean Python environment before pushing changes.
- Keep the registry and `configs/*.json`; they are source configuration, not data.
- Do not include generated outputs, datasets, review-only aggregates, clinical
  documents, credentials or date/session crosswalks. Do not force-add ignored data.
- Select the software license before making the repository public; none is
  included automatically. Dataset licensing and aggregate release approval are
  separate from publishing this code.
