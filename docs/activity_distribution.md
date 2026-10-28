# Activity Distribution: Reproduction Method

Entry point: `figures/fig_activity_distribution.py`.
Manuscript reference: `fig:pieActivity`.

## Input and Scope

Read the public metadata and every `accepted` recording CSV. Require a verified
duration and the declared relative 100 Hz grid. Read columns by name:
`sample_index`, `time_s`, `state_labels`. Check each consumed file's SHA-256
against the public dataset index; verify metadata and content hashes as well.
No original MAT, sparse annotation cache, source paths, calendar dates or private
crosswalk are needed. Native-clock records contribute only documented file/sample
counts, never assumed recording hours. Their payloads are not read by this plot.

`state_labels` is already a dense decoded stream. Repeated states and samples
between sparse raw transitions therefore count toward occupancy. Do not interpret
raw four/five-digit transitions again or use their first digit as an activity.

## Time Support

For an accepted recording with verified source-grid duration D seconds, let
M = round(1000 D) be its integer duration in milliseconds. The ceil-resampled
output must contain N = ceil(M / 10) samples. Its first N-1 bins contribute
10 ms each; its last contributes M - 10(N-1) ms, between 1 and 10 ms. Validate
the sample indices and time grid, not just the row count.

For example, a 13 ms source recording has two output samples at 0 and 0.01 s.
They represent 10 ms and 3 ms, not 20 ms. This clips support at the original
recording boundary without deleting or changing any sample. Integer arithmetic
ensures assigned + unknown + outside time equals full verified time exactly.
This is accounting precision, not a claim of millisecond-accurate annotations.

## Categories and Denominators

- Integral states 10..99 map to decades 1X..9X using integer division by 10.
- Negative or nonfinite labels are unknown; the release normally uses -1.
- Other integral states, including zero and transition-like values, are outside
  1X-9X. Nonintegral or out-of-int16 labels fail validation rather than truncate.
- Preserve every verified recording regardless of sensor masks, available gait
  cycles, participant identity or whether a signal is zero/flat.

The default `verified_time` denominator includes all three categories. The
optional `assigned_activity` denominator conditions on 1X-9X only, without
removing missingness from the accompanying tables/audit. This is pooled time
within family, not equal weighting of participants, visits, files or events.
Small percentages can have their text hidden without dropping their slices.

Colors match the historical activity-decade palette. Groups 8X and 9X retain
their codes without unsupported semantic names. A passive-mode state is not
independent evidence of measured torque or motor power.

## Outputs and Limitations

The renderer produces a single four-family pie figure in PNG and SVG. Numerical
CSV/JSON files preserve sample counts, integer milliseconds, hours and both
fractions. The record audit identifies excluded native files and distinguishes
their index-declared hashes from the actual hashes checked for accepted files.
The execution manifest binds input data, code/config versions, runtime versions
and output hashes. Nonempty output folders and dataset-contained output paths
are refused.

Labels inherit the dataset's approximate PVD-to-DAQ association and state
reconstruction. They are not independent activity ground truth. Unknown labels
are not subdivided into missing-field versus all-zero-source causes from the
dense stream alone. Native durations are unresolved. The figure intentionally
does not reproduce historical transition-frequency pie values, and does not
alter the dataset or manuscript.
