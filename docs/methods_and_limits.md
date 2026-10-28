# Reproduction Methods and Limits

## Source and Scope

The ten data-driven manuscript figures are traced to generators in
`explore_multiple_datasets/`. The filenames and SHA-256 snapshots are recorded in
`configs/source_provenance.json` and `figure_registry.json`; those files identify
the porting sources, not runtime dependencies. The standalone code reads public
CSV files, not the old MAT archive, pickle datasets or cached exploratory results.

The owner excluded the overview diagram and clinical-document illustration from
this work and requested leaving the curated hardware and demographic tables
unchanged. No source data were invented for these four artifacts.

## Shared Cycle Inventory

`common/cycles.py` scans every verified-clock recording independently. It uses
the already decoded dense state labels. The configured phase lists are
21/22/23/24, 31/33/39/34, 41/42/43/44, 51/52/53/54, 61/62/63/64 and
70/71/72/73. Start labels are chosen using configuration-wide **state-entry**
counts, not the number of held samples. When 70 is absent, passive walking can
start at 71; it is not relabeled as 2X.

The legacy group-entry/start-state-recurrence logic is retained: segments can end
at another anchor, a group exit or a file boundary. Endpoint-state presence is
required where qualifying segments exist in that configuration/activity;
otherwise the legacy fallback is explicitly recorded. The policy does not prove
ordered visitation of all four phases. It can retain group/file-edge fragments,
so counts are **accepted gait segments**, not independently verified heel-strike
strides. No segment can bridge two recording files. Long segments above the
configuration/activity 95th duration percentile are excluded.

The four reviewed Fz exceptions are Fox-0.2+PolyA-1.1 in 5X,
Fox-flip-0.1+tf in 6X, HK-1.1+PolyA-1.2 in 5X and HK-1.2+PolyA-1.2 in 6X.
They split at each upward smoothed-Fz threshold crossing while remaining in
51/61. The HK-1.1 threshold is recomputed from other HK 5X cycle-start Fz values,
not copied as an old absolute number. The legacy 21-row smoother and 10-row
minimum become durations using verified recording duration divided by original
PVD row count, then are converted to the 100 Hz grid. This is an **approximate
row-ratio transfer**, not measured PVD timing or an exact equivalence to an old
phase-resampled pickle. Every threshold, period, cutoff, boundary type,
fallback and rejection is exported. These exceptional cases merit inspection
before interpreting small-sample activity means.

Each retained whole segment is linearly resampled once to 100 points. Individual
phases are not normalized separately and concatenated. A signal is eligible only
if finite and valid throughout that segment; missing gaps are not filled. The
same inventory feeds sensor/current grids, step heatmaps and walking amplitudes.
Channel-specific contributing counts are exported. Sensor count heatmaps count
segments with at least one eligible sensor, not eight complete channels.

## Signals and Summaries

The eight named sensor columns and two aligned current columns are used as
released. No new indices, sign inversions, physiological calibration, saturation
removal or normalization of amplitudes is applied. Unverified VU `My` and
conflicted OSL `My` remain missing. Native-clock files are excluded from
verified-time/cycle calculations, not deleted from the dataset.

An all-zero ankle-current segment is excluded **only from the ankle-current
summary**, retaining its knee contribution. Source values and dataset masks are
unchanged. The unresolved Goldie V0 knee-current polarity remains unavailable.

Sensor/current curves are means of eligible normalized segments, with family
colors and configuration shades. All activity columns share each family's
sensor-specific range, and all four family zeros coincide. Different axis spans
are display choices, not conversion factors. Dashed 7X curves overlay the
walking panel without being concatenated with 2X.

Amplitude heatmaps show per-configuration medians of per-segment peak-to-peak
range and time mean on the 100-point 2X/7X representations; 10th/90th percentiles
are exported. These are real statistics of the plotted data, not y-axis ranges.
Heatmap `nan` means unavailable, not zero. Raw counts annotate step heatmaps;
only their colors are row-normalized, with the color maximum fitted to the
actual plotted range. Family and subleg heatmaps have the same physical cell size.

Controller parameters use the six named stiffness/damping/equilibrium-angle
columns. Finite samples are averaged within each contiguous state run, then run
means receive equal weight within configuration/state. Error bars are population
standard deviations of run means. They do not isolate clinician tuning or
subject-level variation. State-run averaging at the released resolution replaces
the historical phase-chunk representation, and need not reproduce its numbers
exactly. Similarity is signed Pearson correlation of family profiles over common
states, with configuration means weighted equally within family. Constants and
fewer than two common states are undefined; correlations from only two states
are necessarily extreme and should not be treated as strong evidence.

## Time, Privacy and Representative Selections

Activity time is pooled decoded-state occupancy, including held samples between
events. Integer milliseconds clip the terminal 100 Hz bin to original verified
source support. Unknown and outside-decade samples remain in the denominator;
the normalized calendar panel is explicitly conditional on assigned 1X-9X time.
No frequency is guessed for native exceptions. Calendar plots do not use
`struct.time` elapsed duration.

The public participant timeline uses elapsed days from each participant's first
observed visit, not calendar dates. Calendar figures accept only separate
month/quarter aggregate schemas. The owner authorized preparing these internally
for review; this is not approval to publish them. An explicit
`--allow-review-only` flag is required to render unapproved inputs. Private
crosswalks/preparation code are not dependencies or contents of the public code
folder. Aggregate dates still require disclosure review.

For representative traces, all eligible triples in a deterministic per-family
recording shortlist are compared by knee-angle shape. One global translation
per family is estimated on the third selected cycle. Original continuous-file
context fills shifted edges; there is no cycle concatenation or time warp.
The display is limited to the common post-shift window around the three reference
cycles. Dashed markers refer only to HK reference boundaries. The other devices'
selected triples and shifts are recorded separately; they need not hit identical
cycle boundaries in real time.

In the current candidate, no common participant has three consecutive eligible,
labeled 2X cycles in all four families. The default therefore fails rather than
mix participants silently. An explicit `--allow-mixed-participants` produces a
clearly labeled alternative with participant IDs and public recording selections.
This is not equivalent to the historical same-participant attempt and is not an
unbiased sample of the dataset. All displayed traces use the released 100 Hz
signals rather than the original 1 kHz archive.

## Tables and Validation

Device counts are unique public source-session groups by configuration, not
visit days. Participant tables count distinct shared visit groups, with source
sessions reported separately. Family visit counts need not add to unique visits.
The structure table describes continuous CSVs and separate native exceptions,
not obsolete v16 windows. Calendar years are omitted from metadata-only session
tables because they cannot be inferred from the approved public relative timing.

Each run exports code/input/output hashes and refuses overwriting prior outputs
or writing inside the dataset. Synthetic tests cover boundary definitions,
partial support bins, masks, current signs/zero ankles, zero-aligned axes,
aggregate privacy gates and standalone execution. Full-dataset output checks
reconcile inventory counts and scientific summaries. These checks are not proof
of physical channel identity, accurate heel-strike detection, clinical validity,
consent clearance or a publication-ready scientific interpretation.
