#!/usr/bin/env python3
"""Reconcile generated full-run inventories, tables and scientific summaries."""
import argparse
import csv
import json
import sys
from collections import Counter,defaultdict
from pathlib import Path

import numpy as np

from common.artifacts import write_json
from common.cycles import CURRENTS,SENSORS,load_analysis
from common.metadata import FAMILIES,digest,load_public_metadata
from common.recordings import public_checksums


def read(path):
    with Path(path).open(encoding="utf-8",newline="") as f:
        return list(csv.DictReader(f))


def validate(dataset,output,analysis_dir):
    root,_,rows=load_public_metadata(dataset)
    output=Path(output);analysis_dir=Path(analysis_dir)
    info,data=load_analysis(dataset,analysis_dir)
    checks=[]
    def check(condition,message):
        if not bool(condition):raise ValueError(message)
        checks.append(message)
    hashes=public_checksums(root)
    accepted={int(r["record_id"]):r for r in rows if r["status"]=="accepted"}
    audit=read(analysis_dir/"recording_hashes.csv")
    check(len(audit)==len(accepted) and len({int(r["record_id"]) for r in audit})==len(accepted),"All verified recordings have one sensor/current hash audit row")
    for r in audit:
        original=accepted[int(r["record_id"])]
        if r["sensor_sha256"]!=hashes[original["csv_path"]] or r["current_sha256"]!=hashes[original["current_csv_path"]]:
            raise ValueError("Audited hashes differ from dataset index")
    check(True,"Every audited sensor/current hash matches the public index")
    ci={r["code"]:k for k,r in enumerate(info["configurations"])}
    segmented,sensors,signal_counts=Counter(),Counter(),Counter()
    fragment,zero_ankle,exception_counts=Counter(),0,Counter()
    candidate_rows=0
    with (analysis_dir/"cycle_inventory.csv").open(encoding="utf-8") as f:
        for c in csv.DictReader(f):
            candidate_rows+=1
            rid=int(c["record_id"]);s,e=int(c["start"]),int(c["end"])
            if rid not in accepted or not 0<=s<e<=int(accepted[rid]["rows"]):
                raise ValueError("Segment crosses recording boundary")
            if c["accepted"]!="True":continue
            k,d=ci[c["configuration"]],int(c["decade"])
            segmented[(k,d)]+=1
            if c["contributes_sensor_grid"]=="True":sensors[(k,d)]+=1
            for j,eligible in enumerate(c["signal_eligibility"]):
                signal_counts[(k,d,j)]+=int(eligible)
            if c["left_boundary"]!="anchor" or c["right_boundary"]!="anchor":fragment[c["boundary_source"]]+=1
            if c["all_zero_ankle_current_excluded"]=="True":
                zero_ankle+=1
                if c["signal_eligibility"][9]!="0":raise ValueError("Zero ankle was counted as eligible")
            if c["boundary_source"]=="fz_start_state_upcrossing":
                exception_counts[(c["configuration"],d)]+=1
    check(sum(segmented.values())==info["accepted_segments"],"Accepted inventory segments reconcile with analysis summary")
    check(sum(sensors.values())==info["sensor_contributing_segments"],"Sensor-contributing inventory counts reconcile")
    for r in read(analysis_dir/"cycle_counts.csv"):
        k,d=ci[r["configuration"]],int(r["decade"])
        if segmented[(k,d)]!=int(r["segmented_cycles"]) or sensors[(k,d)]!=int(r["sensor_contributing_cycles"]):
            raise ValueError("Cycle count table differs from inventory")
        for j,name in enumerate((*SENSORS,*CURRENTS)):
            n=signal_counts[(k,d,j)]
            if n!=int(r[name+"_cycles"]) or not np.all(data["n"][k,d-2,:,j]==n):
                raise ValueError("Signal-specific counts differ from inventory")
    check(True,"All ten signal counts match inventory and normalized sufficient statistics")
    check(np.all(data["n"]>=0),"No negative cycle sample counts")
    mean=np.divide(data["total"],data["n"],out=np.full(data["total"].shape,np.nan),where=data["n"]>0)
    check(not np.any(np.isinf(mean)),"Mean profiles contain finite values or explicit missingness, never infinity")
    amp=data["amplitude"]
    for index in (0,3):
        median,low,high=amp[:,index,:],amp[:,index+1,:],amp[:,index+2,:]
        good=np.isfinite(median)
        check(np.all(low[good]<=median[good]) and np.all(median[good]<=high[good]),f"Amplitude metric {index}: p10 <= median <= p90")
    check(np.all(amp[:,0,:][np.isfinite(amp[:,0,:])]>=0),"Peak-to-peak amplitudes are nonnegative")
    activity=json.loads((output/"activity_distribution/activity_distribution.json").read_text())
    ms=sum(round(float(r["verified_grid_duration_s"])*1000) for r in accepted.values())
    check(activity["verified_milliseconds"]==ms,"Activity time equals full verified source support")
    quarter=output/"activity_over_time/quarterly_totals.csv"
    if quarter.is_file():
        qq=read(quarter)
        check(abs(sum(float(r["verified_hours"]) for r in qq)-ms/3600000)<1e-10,"Quarterly time reconciles with activity and metadata totals")
        check(sum(int(r["native_files_without_duration"]) for r in qq)==len(rows)-len(accepted),"Native-clock files are counted but assigned no hours")
    tables=read(output/"table_device_sessions/tab_legs.csv")
    totals={f:sum(int(r["source_sessions"]) for r in tables if r["family"]==f) for f in FAMILIES}
    expected={f:len({r["session_id"] for r in rows if r["family"]==f and r["session_id"]}) for f in FAMILIES}
    check(totals==expected,"Four-family session table reconciles with public metadata")
    heatmap=read(output/"step_counts/gait_phase_step_count_heatmap_legs.csv")
    family_counts=defaultdict(lambda:np.zeros(5,dtype=int))
    for (k,d),n in sensors.items():family_counts[info["configurations"][k]["family"]][0 if d in (2,7) else d-2]+=n
    activity_names=["Walking (2X / 7X)","Stair ascent (3X)","Stair descent (4X)","Ramp ascent (5X)","Ramp descent (6X)"]
    for r in heatmap:
        if family_counts[r["family"]][activity_names.index(r["activity"])]!=int(r["steps"]):
            raise ValueError("Heatmap counts differ from sensor inventory")
    check(True,"Family heatmap annotations match the sensor-grid segment inventory")
    for path in sorted(output.rglob("execution_manifest.json")):
        execution=json.loads(path.read_text())
        for name,sha in execution.get("outputs",{}).items():
            if digest(path.parent/name)!=sha:raise ValueError("Output hash mismatch: "+str(path.parent/name))
    check(True,"Generated artifact hashes match their execution manifests")
    warnings=["No independent validation of true heel-strike timing, physical units, channel identity or clinical ground truth.",
              "Partial/group-edge segments and endpoint completeness fallbacks are retained by the documented legacy policy.",
              "Representative overlay uses an explicit mixed-participant alternative; same-participant labeled coverage is unavailable.",
              "Calendar aggregate inputs and outputs are review-only, not approved for publication."]
    low_count=[{"configuration":code,"decade":d,"accepted_segments":n} for (code,d),n in exception_counts.items() if n<10]
    if low_count:warnings.append("Some reviewed Fz exception cells have fewer than ten retained segments; inspect the inventory before interpretation.")
    return {"schema_version":1,"checks_passed":checks,"verified_recordings":len(accepted),"native_recordings_not_assigned_hours":len(rows)-len(accepted),
            "candidate_segments":candidate_rows,"accepted_segments":sum(segmented.values()),"sensor_contributing_segments":sum(sensors.values()),
            "non_anchor_bounded_accepted_segments_by_source":dict(fragment),"ankle_zero_segments_excluded_only_from_ankle":zero_ankle,
            "family_session_counts":totals,"verified_hours":ms/3600000,"low_count_fz_exceptions":low_count,"warnings":warnings,
            "dataset_modified":False,"manuscript_modified":False}


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset",required=True)
    parser.add_argument("--run-dir",required=True)
    parser.add_argument("--analysis-dir",required=True)
    parser.add_argument("--report",required=True,help="New JSON report path")
    args=parser.parse_args(argv)
    try:
        report=Path(args.report).resolve();dataset=Path(args.dataset).resolve()
        if report.is_relative_to(dataset) or report.exists():raise ValueError("Report must be new and outside dataset")
        result=validate(args.dataset,args.run_dir,args.analysis_dir)
        report.parent.mkdir(parents=True,exist_ok=True);write_json(report,result)
        print(json.dumps(result,indent=2))
    except (OSError,ValueError) as exc:parser.error(str(exc))


if __name__=="__main__":sys.exit(main())
