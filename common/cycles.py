"""Whole-cycle inventory adapted from the reviewed exploration gait-grid code.

No legacy pickle imports, channel reassignment, polarity changes or physical-unit
conversion. Boundaries never cross recording files. Statistics use masks strictly:
a channel must be finite/valid throughout a cycle; gaps are not interpolated away.
"""

import argparse
import csv
import json
import time
from collections import Counter, defaultdict
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from .activities import write_csv
from .artifacts import manifest, new_output, write_json
from .metadata import FAMILIES, digest, load_public_metadata
from .recordings import public_checksums, read_named_columns, verified_time_support

SENSORS = ("Fz", "My", "KneeAngle", "KneeVel", "AnkleAngle", "AnkleVel", "ThighAngle", "ShankAngle")
CURRENTS = ("KneeActualCurrent", "AnkleActualCurrent")
PARAMETERS = ("KneeStiffness", "KneeDamping", "KneeEqAngle", "AnkleStiffness", "AnkleDamping", "AnkleEqAngle")
STATES = {2: (21,22,23,24), 3: (31,33,39,34), 4: (41,42,43,44),
          5: (51,52,53,54), 6: (61,62,63,64), 7: (70,71,72,73)}
SPECIAL = {("Fox-0.2+PolyA-1.1", 5): 51, ("Fox-flip-0.1+tf", 6): 61,
           ("HK-1.1+PolyA-1.2", 5): 51, ("HK-1.2+PolyA-1.2", 6): 61}
VERSION = "public_whole_cycle_1.0"


def state_runs(labels):
    finite = np.isfinite(labels)
    if np.any(labels[finite] != np.rint(labels[finite])):
        raise ValueError("Nonintegral state")
    states = np.where(finite, labels, -1).astype(np.int32)
    if not len(states):
        return np.empty((0,3), dtype=np.int32)
    starts = np.r_[0, np.flatnonzero(states[1:] != states[:-1])+1]
    return np.column_stack((starts, np.r_[starts[1:], len(states)], states[starts])).astype(np.int32)


def regular_segments(runs, group, anchor):
    """Legacy group-entry/start-state splitting, including audited edge fragments."""
    result, start, seen, left = [], None, set(), ""
    for a, b, state in runs:
        a, b, state = int(a), int(b), int(state)
        if start is not None and (state == anchor or state not in group):
            result.append((start, a, tuple(sorted(seen)), left, "anchor" if state == anchor else "group_exit"))
            start, seen = None, set()
        if state in group:
            if start is None:
                start, left = a, "anchor" if state == anchor and a > 0 else "group_or_file_entry"
            seen.add(state)
    if start is not None:
        result.append((start, int(runs[-1,1]), tuple(sorted(seen)), left, "file_end"))
    return result


def choose_anchor(counts, group, decade, min_count=10):
    preferred = group if decade in (6,7) else group[:1]
    for state in preferred:
        if counts[state] >= min_count:
            return state
    return next((state for state in group if counts[state]), None)


def normalized_cycle(values, valid=None, n=100):
    if values.ndim != 2 or len(values) < 2:
        raise ValueError("A cycle needs at least two samples")
    good = np.all(np.isfinite(values), axis=0)
    if valid is not None:
        good &= np.all(valid == 1, axis=0)
    result = np.full((n, values.shape[1]), np.nan)
    x, xx = np.linspace(0,1,len(values)), np.linspace(0,1,n)
    for channel in np.flatnonzero(good):
        result[:,channel] = np.interp(xx, x, values[:,channel])
    return result, good


def smooth_valid(values, width):
    """Centered legacy boxcar, but never bridge missing sensor spans."""
    width = min(len(values), max(1, int(width)))
    kernel = np.ones(width)
    finite = np.isfinite(values)
    sums = np.convolve(np.where(finite,values,0), kernel, mode="same")
    count = np.convolve(finite.astype(float), kernel, mode="same")
    support = np.convolve(np.ones(len(values)), kernel, mode="same")
    return np.divide(sums, count, out=np.full(len(values),np.nan), where=(count == support) & (count > 0))


def fz_segments(labels, fz, group, start_state, pvd_period_s, forced_threshold=None):
    """Every upward crossing in the start state; legacy 21/10 rows -> seconds."""
    if not len(fz) or not np.isfinite(pvd_period_s) or pvd_period_s <= 0:
        return [], None, None, None
    smooth_samples = max(1, int(round(21*pvd_period_s*100)))
    if smooth_samples % 2 == 0:
        smooth_samples += 1
    min_samples = max(2, int(np.ceil(10*pvd_period_s*100-1e-9)))
    y = smooth_valid(fz, smooth_samples)
    mask = np.isin(labels, group)
    a, b = y[(labels == start_state) & mask], y[(labels != start_state) & mask]
    a, b = a[np.isfinite(a)], b[np.isfinite(b)]
    all_y = y[mask & np.isfinite(y)]
    minimum = max(2, int(np.ceil(10*pvd_period_s*100-1e-9)))
    if len(all_y)<minimum:
        return [],None,smooth_samples/100,min_samples/100
    if forced_threshold is not None and np.isfinite(forced_threshold):
        threshold = float(forced_threshold)
    elif len(a) >= minimum and len(b) >= minimum:
        threshold = float((np.median(a)+np.median(b))/2)
    elif len(all_y) >= minimum:
        threshold = float(np.quantile(all_y,.60))
    else:
        return [], None, smooth_samples/100, min_samples/100
    result = []
    for left, right, value in state_runs(mask.astype(int)):
        if value != 1:
            continue
        jj = np.arange(int(left)+1, int(right))
        crossed = jj[(labels[jj] == start_state) & (labels[jj-1] == start_state)
                     & (y[jj-1] <= threshold) & (y[jj] > threshold)]
        bounds = [int(left), *map(int,crossed), int(right)]
        for index, (s,e) in enumerate(zip(bounds[:-1],bounds[1:])):
            result.append((s,e,tuple(map(int,np.unique(labels[s:e]))),
                           "fz_crossing" if index else "group_or_file_entry",
                           "fz_crossing" if index < len(bounds)-2 else "group_or_file_exit"))
    return result, threshold, smooth_samples/100, min_samples/100


def inspect(task):
    root, row, sha, pvd_rows = task
    data, actual = read_named_columns(root,row,("sample_index","time_s","state_labels","Fz","Fz_valid"),sha)
    verified_time_support(row,data[:,0],data[:,1])
    runs = state_runs(data[:,2])
    fz = np.where(data[:,4] == 1, data[:,3], np.nan)
    cfg = row["configuration_code"]
    refs = []
    if row["family"] == "HK" and cfg != "HK-1.1+PolyA-1.2":
        for s,e,seen,_,_ in regular_segments(runs,STATES[5],51):
            if 51 in seen and 54 in seen and e-s > 1 and np.isfinite(fz[s]):
                refs.append((e-s, float(fz[s])))
    special = any(c == cfg for c,_ in SPECIAL)
    return {"record_id": int(row["record_id"]), "runs": runs, "sha256": actual,
            "refs": refs, "fz": fz if special else None,
            "pvd_period_s": float(row["verified_grid_duration_s"])/pvd_rows if pvd_rows else None}


def sum_block(values):
    finite = np.isfinite(values)
    return np.where(finite,values,0).sum(axis=0), np.where(finite,values**2,0).sum(axis=0), finite.sum(axis=0)


def analyze_record(task):
    root,row,sha,current_sha,cycles = task
    columns = ("sample_index","time_s",*SENSORS,*(s+"_valid" for s in SENSORS),*PARAMETERS,"state_labels")
    data,actual = read_named_columns(root,row,columns,sha)
    verified_time_support(row,data[:,0],data[:,1])
    current_row = dict(row, csv_path=row["current_csv_path"])
    currents, current_hash = read_named_columns(root,current_row,("sample_index","time_s",*CURRENTS,*(s+"_valid" for s in CURRENTS)),current_sha)
    if not np.array_equal(data[:,:2],currents[:,:2]):
        raise ValueError("Sensor/current sample grids do not match")
    signals = np.column_stack((data[:,2:10],currents[:,2:4]))
    masks = np.column_stack((data[:,10:18],currents[:,4:6]))
    if np.any((masks != 0) & (masks != 1)):
        raise ValueError("Invalid binary signal mask")
    groups, walk, inventory = {}, [], []
    for cycle in cycles:
        c = dict(cycle)
        eligible = np.zeros(10,dtype=bool)
        c["all_zero_ankle_current_excluded"] = False
        if c["accepted"]:
            s,e = c["start"],c["end"]
            norm,eligible = normalized_cycle(signals[s:e],masks[s:e])
            # This is a plot eligibility rule, not a dataset modification.
            ankle_zero = bool(eligible[9] and np.all(signals[s:e,9] == 0))
            if ankle_zero:
                norm[:,9] = np.nan
                eligible[9] = False
            c["all_zero_ankle_current_excluded"] = ankle_zero
            decade = c["decade"]
            if decade not in groups:
                groups[decade] = [np.zeros((100,10)),np.zeros((100,10)),np.zeros((100,10),dtype=np.int64)]
            finite = np.isfinite(norm)
            groups[decade][0] += np.where(finite,norm,0)
            groups[decade][1] += np.where(finite,norm**2,0)
            groups[decade][2] += finite
            if decade in (2,7):
                means,amp = np.full(8,np.nan),np.full(8,np.nan)
                for k in np.flatnonzero(eligible[:8]):
                    means[k],amp[k] = norm[:,k].mean(),np.ptp(norm[:,k])
                walk.append(np.r_[means,amp])
        c["signal_eligibility"] = "".join("1" if x else "0" for x in eligible)
        c["contributes_sensor_grid"] = bool(c["accepted"] and np.any(eligible[:8]))
        inventory.append(c)
    phase = {}
    for s,e,state in state_runs(data[:,-1]):
        state = int(state)
        if state not in {x for group in STATES.values() for x in group}:
            continue
        values = data[int(s):int(e),18:24]
        count = np.isfinite(values).sum(axis=0)
        mean = np.divide(np.nansum(values,axis=0),count,out=np.full(6,np.nan),where=count > 0)
        if state not in phase:
            phase[state] = [np.zeros(6),np.zeros(6),np.zeros(6,dtype=np.int64)]
        good = np.isfinite(mean)
        phase[state][0] += np.where(good,mean,0)
        phase[state][1] += np.where(good,mean**2,0)
        phase[state][2] += good
    return int(row["record_id"]), groups, phase, np.asarray(walk).reshape((-1,16)), inventory, actual,current_hash


def build(dataset, output, workers=4):
    if workers < 1:
        raise ValueError("workers must be positive")
    root,content,rows = load_public_metadata(dataset)
    expected = public_checksums(root)
    if expected.get("records.jsonl") != digest(root/"records.jsonl"):
        raise ValueError("Public ledger checksum mismatch")
    hashes = {name:digest(root/name) for name in ("metadata.csv","DATASET_CONTENT.json","checksums.sha256","records.jsonl")}
    output = new_output(root,output)
    accepted = [r for r in rows if r["status"] == "accepted"]
    by_id = {int(r["record_id"]):r for r in accepted}
    pvd_counts = {}
    with (root/"records.jsonl").open(encoding="utf-8") as stream:
        for line in stream:
            record = json.loads(line)
            shape = record.get("annotation_array_shapes",{}).get("raw_event_labels",[])
            pvd_counts[int(record["record_id"])] = shape[0] if shape else 0
    configs = sorted({(r["family"],r["configuration_code"]) for r in accepted}, key=lambda x:(FAMILIES.index(x[0]),x[1]))
    ci = {code:i for i,(_,code) in enumerate(configs)}
    if len(ci)!=len(configs):
        raise ValueError("Configuration codes must be unique across families")
    counts, refs, scans = defaultdict(Counter),defaultdict(list),{}
    tasks = ((root,r,expected[r["csv_path"]],pvd_counts[int(r["record_id"])]) for r in accepted)
    start, last = time.monotonic(),time.monotonic()
    print(f"Cycle inventory: scanning all {len(accepted):,} verified recordings",flush=True)
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for scan in pool.map(inspect,tasks,chunksize=16):
            rid = scan["record_id"]
            row = by_id[rid]
            counts[row["configuration_code"]].update(map(int,scan["runs"][:,2]))
            refs[row["configuration_code"]].extend(scan.pop("refs"))
            scans[rid] = scan
            if time.monotonic()-last > 20:
                print(f"Boundaries: {len(scans):,}/{len(accepted):,}; {time.monotonic()-start:.0f}s",flush=True)
                last = time.monotonic()
    # Recompute the reviewed HK 5X threshold from released reference channels.
    fz0 = []
    for code,values in refs.items():
        if not values:
            continue
        cutoff = np.quantile([v[0] for v in values],.95)
        fz0.extend(v[1] for v in values if v[0] <= cutoff)
    forced = float(np.median(fz0)) if fz0 else None
    anchors = {(code,d):choose_anchor(counts[code],group,d) for _,code in configs for d,group in STATES.items()}
    inventories, strict_available = {},Counter()
    durations = defaultdict(list)
    for rid,scan in scans.items():
        row,cycles = by_id[rid],[]
        code = row["configuration_code"]
        for d,group in STATES.items():
            anchor = anchors[(code,d)]
            threshold,smooth_s,min_s = None,None,.02
            if (code,d) in SPECIAL:
                labels = np.empty(int(row["rows"]),dtype=int)
                for a,b,state in scan["runs"]:
                    labels[a:b] = state
                period = scan["pvd_period_s"]
                segments,threshold,smooth_s,min_s = fz_segments(labels,scan["fz"],group,SPECIAL[(code,d)],period or np.nan,
                    forced if (code,d) == ("HK-1.1+PolyA-1.2",5) else None)
                source = "fz_start_state_upcrossing"
            else:
                segments = regular_segments(scan["runs"],group,anchor) if anchor is not None else []
                source = "state_recurrence"
            present = [s for s in group if counts[code][s]]
            first,last_state = (present[0],present[-1]) if present else (None,None)
            for s,e,seen,left,right in segments:
                strict = first in seen and last_state in seen and len(seen) >= 2
                cycle = {"record_id":rid,"family":row["family"],"configuration":code,"decade":d,"start":s,"end":e,
                         "duration_s":(e-s)/100,"anchor":anchor,"boundary_source":source,"left_boundary":left,"right_boundary":right,
                         "states":";".join(map(str,seen)),"strict_complete":strict,"threshold":threshold,
                         "smoothing_s":smooth_s,"min_segment_s":min_s,"pvd_period_s":scan["pvd_period_s"],"accepted":False,"rejection":""}
                cycles.append(cycle)
                if strict and (e-s)/100 >= min_s:
                    strict_available[(code,d)] += 1
        inventories[rid] = cycles
        scan.pop("fz",None)
    for rid,cycles in inventories.items():
        for c in cycles:
            key = (c["configuration"],c["decade"])
            c["completeness_fallback"] = not bool(strict_available[key])
            if c["duration_s"] < c["min_segment_s"]:
                c["rejection"] = "below_minimum_duration"
            elif strict_available[key] and not c["strict_complete"]:
                c["rejection"] = "missing_endpoint_state"
            else:
                durations[key].append(c["duration_s"])
    cutoffs = {k:float(np.quantile(v,.95)) for k,v in durations.items()}
    for cycles in inventories.values():
        for c in cycles:
            c["duration_cutoff_s"] = cutoffs.get((c["configuration"],c["decade"]))
            if not c["rejection"] and c["duration_s"] > c["duration_cutoff_s"]:
                c["rejection"] = "above_95th_duration_percentile"
            c["accepted"] = not bool(c["rejection"])
    del scans
    totals = np.zeros((len(configs),6,100,10))
    squares = np.zeros_like(totals)
    numbers = np.zeros(totals.shape,dtype=np.int64)
    phase_sum = np.zeros((len(configs),100,6))
    phase_square = np.zeros_like(phase_sum)
    phase_n = np.zeros(phase_sum.shape,dtype=np.int64)
    walking = defaultdict(list)
    record_hashes,cycle_counts,eligible_counts,rejections = [],Counter(),Counter(),Counter()
    tasks = ((root,r,expected[r["csv_path"]],expected[r["current_csv_path"]],inventories[int(r["record_id"])]) for r in accepted)
    done,last = 0,time.monotonic()
    with (output/"cycle_inventory.csv").open("w",encoding="utf-8",newline="") as stream, ProcessPoolExecutor(max_workers=workers) as pool:
        writer = None
        for rid,groups,phases,walk,cycles,sha,current_sha in pool.map(analyze_record,tasks,chunksize=8):
            row = by_id[rid]
            k = ci[row["configuration_code"]]
            for d,(s,ss,n) in groups.items():
                totals[k,d-2] += s
                squares[k,d-2] += ss
                numbers[k,d-2] += n
            for state,(s,ss,n) in phases.items():
                phase_sum[k,state] += s
                phase_square[k,state] += ss
                phase_n[k,state] += n
            if len(walk):
                walking[k].append(walk)
            for c in cycles:
                if writer is None:
                    writer = csv.DictWriter(stream,fieldnames=list(c),lineterminator="\n")
                    writer.writeheader()
                writer.writerow(c)
                if c["accepted"]:
                    cycle_counts[(k,c["decade"])] += 1
                    if c["contributes_sensor_grid"]:
                        eligible_counts[(k,c["decade"])] += 1
                else:
                    rejections[c["rejection"]] += 1
            record_hashes.append({"record_id":rid,"sensor_sha256":sha,"current_sha256":current_sha})
            done += 1
            if time.monotonic()-last > 20:
                print(f"Signals/parameters/currents: {done:,}/{len(accepted):,}; {time.monotonic()-start:.0f}s",flush=True)
                last = time.monotonic()
    amplitude = np.full((len(configs),6,8),np.nan)
    for k,blocks in walking.items():
        vals = np.concatenate(blocks)
        for j in range(8):
            for offset,dest in ((0,3),(8,0)):
                v = vals[:,j+offset]
                v = v[np.isfinite(v)]
                if len(v):
                    amplitude[k,dest:dest+3,j] = np.quantile(v,[.5,.1,.9])
    np.savez_compressed(output/"analysis.npz",total=totals,square=squares,n=numbers,
                        phase_total=phase_sum,phase_square=phase_square,phase_n=phase_n,amplitude=amplitude)
    count_rows = [{"family":f,"configuration":code,"decade":d,"segmented_cycles":cycle_counts[(k,d)],
                   "sensor_contributing_cycles":eligible_counts[(k,d)],
                   **{name+"_cycles":int(numbers[k,d-2,0,j]) for j,name in enumerate((*SENSORS,*CURRENTS))}}
                  for k,(f,code) in enumerate(configs) for d in STATES]
    write_csv(output/"cycle_counts.csv",count_rows)
    write_csv(output/"recording_hashes.csv",record_hashes)
    write_csv(output/"boundary_rules.csv",[{"configuration":code,"decade":d,"anchor":anchors[(code,d)],
              "duration_cutoff_s":cutoffs.get((code,d)),"strict_cycles":strict_available[(code,d)],
              "completeness_fallback":not bool(strict_available[(code,d)])} for _,code in configs for d in STATES])
    summary = {"schema_version":VERSION,"dataset_schema":content["schema_version"],"input_hashes":hashes,
               "configurations":[{"family":f,"code":code} for f,code in configs],"sensors":list(SENSORS),"currents":list(CURRENTS),
               "parameters":list(PARAMETERS),"states":{str(k):list(v) for k,v in STATES.items()},
               "verified_recordings":len(accepted),"native_clock_recordings_excluded":len(rows)-len(accepted),
               "accepted_segments":sum(cycle_counts.values()),"sensor_contributing_segments":sum(eligible_counts.values()),
               "rejected_segments":dict(rejections),"hk_5x_reference_fz0_threshold":forced,"reference_fz0_cycles":len(fz0),
               "normalization_points":100,"duration_quantile":.95,"elapsed_s":time.monotonic()-start,
               "methods":{
                   "segmentation":"Within each recording; group entry to start-state recurrence/group exit/file end. Entry/exit fragments are retained only under the exported endpoint-presence/fallback and length policy; not all counted segments are independently validated heel-strike strides.",
                   "anchors":"Configuration-wide state-entry counts, not dense sample counts; prefer 21/31/41/51, ordered 61..64 and 70..73; fallback first present. Actual 7X endpoints are the first/last configured states observed per configuration.",
                   "fz":"Four reviewed configuration/activity exceptions. Every smoothed upward Fz crossing within 51/61. Minimum/smoothing durations = 10/21 original annotation rows times verified recording duration / original annotation row count. This row-ratio is an approximate alignment-derived period, not a measured PVD clock. Missing period or Fz means no special-case segments.",
                   "hk_5x":"HK-1.1+PolyA-1.2 threshold = median first Fz from strict other-HK 5X cycles after per-configuration 95th length filtering, recomputed in released source units.",
                   "filter":"Endpoint-state presence when available; otherwise configuration/activity fallback (explicit in inventory), then within-configuration/activity top 5% duration exclusion. Whole-cycle linear normalization once to 100 points.",
                   "signal_masks":"Channel eligible only if finite and valid for the entire segment; no interpolation across invalid gaps. Missing signals remain NaN. All-zero ankle current segments omitted only for ankle, knee retained.",
                   "parameters":"Mean of finite samples within each contiguous state run, then equal weighting of run means within configuration/state. Population standard deviation; not participant-balanced or clinical tuning variance alone.",
                   "amplitude":"2X and 7X eligible segments pooled, per-cycle mean and peak-to-peak on 100 normalized samples; per-configuration median and 10th/90th percentiles. Counts have channel-specific eligibility.",
                   "units":"Uncalibrated source units; no new signs, calibration or reassignment. Corrected/masked release values can legitimately differ from historical exploratory figures."}}
    for name,sha in hashes.items():
        if digest(root/name) != sha:
            raise ValueError("Dataset metadata changed during analysis")
    write_json(output/"analysis.json",summary)
    text = ["# Shared Public CSV Analysis","",*[("## "+k+"\n\n"+v+"\n") for k,v in summary["methods"].items()],
            f"Verified recordings: {len(accepted):,}. Native-clock recordings excluded: {len(rows)-len(accepted):,}.",
            f"Accepted segments: {sum(cycle_counts.values()):,}; with at least one eligible sensor: {sum(eligible_counts.values()):,}.",
            "No date inputs, original MAT files or historical pickle datasets were used. Hashes verify all sensor/current CSVs read. This does not validate physical channel identity or true heel-strike timing.",""]
    (output/"analysis.md").write_text("\n".join(text),encoding="utf-8")
    manifest(output,"shared_cycle_analysis",hashes,extra={"cache_schema":VERSION,"recordings_hashed":done})
    print(json.dumps({k:summary[k] for k in ("verified_recordings","accepted_segments","sensor_contributing_segments","elapsed_s")},indent=2),flush=True)
    return summary


def load_analysis(dataset, directory):
    root,_,_ = load_public_metadata(dataset)
    directory = Path(directory).resolve()
    info = json.loads((directory/"analysis.json").read_text(encoding="utf-8"))
    if info.get("schema_version") != VERSION:
        raise ValueError("Incompatible shared cycle analysis; rebuild it")
    for name,sha in info["input_hashes"].items():
        if digest(root/name) != sha:
            raise ValueError("Shared analysis belongs to a different dataset")
    execution = json.loads((directory/"execution_manifest.json").read_text(encoding="utf-8"))
    for name in ("analysis.npz","analysis.json","cycle_counts.csv","cycle_inventory.csv"):
        if execution["outputs"].get(name) != digest(directory/name):
            raise ValueError("Shared analysis checksum mismatch: "+name)
    data = np.load(directory/"analysis.npz",allow_pickle=False)
    return info,data


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset",required=True)
    parser.add_argument("--output-dir",required=True)
    parser.add_argument("--workers",type=int,default=4)
    args = parser.parse_args(argv)
    try:
        build(args.dataset,args.output_dir,args.workers)
    except (OSError,ValueError) as exc:
        parser.error(str(exc))


if __name__ == "__main__":
    main()
