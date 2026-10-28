#!/usr/bin/env python3
"""Run every in-scope data figure and table; explicitly record excluded inputs."""
import argparse
import json
import subprocess
import sys
from pathlib import Path

from common.artifacts import new_output,write_json
from common.metadata import ROOT,load_registry


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset",required=True)
    parser.add_argument("--output-dir",required=True,help="New batch directory")
    parser.add_argument("--analysis-dir",help="Reuse an existing verified shared analysis instead of rebuilding")
    parser.add_argument("--aggregates-dir",help="Separate calendar aggregate inputs; otherwise calendar figures are skipped explicitly")
    parser.add_argument("--allow-review-only",action="store_true")
    parser.add_argument("--allow-mixed-participants",action="store_true",help="Explicit alternative for representative traces when same-participant coverage is unavailable")
    parser.add_argument("--workers",type=int,default=4)
    parser.add_argument("--dpi",type=int,default=180)
    args=parser.parse_args(argv)
    dataset=Path(args.dataset).resolve();output=new_output(dataset,args.output_dir)
    analysis=Path(args.analysis_dir).resolve() if args.analysis_dir else output/"shared_analysis"
    results=[]
    def execute(key,command):
        print("\n=== "+key+" ===",flush=True)
        result=subprocess.run([sys.executable,*map(str,command)],cwd=ROOT)
        results.append({"artifact":key,"status":"generated" if result.returncode==0 else "failed","exit_code":result.returncode})
        write_json(output/"batch_report.json",{"artifacts":results,"dataset_modified":False,"manuscript_modified":False})
        return result.returncode==0
    if not args.analysis_dir:
        if not execute("shared_analysis",["-m","common.cycles","--dataset",dataset,"--output-dir",analysis,"--workers",args.workers]):
            return 1
    cycle_ids={"gait_sensor_grid","currents_by_activity","controller_parameters","sensor_amplitude","step_counts","representative_sensor_traces"}
    for figure in load_registry()["figures"]:
        key=figure["id"]
        if not figure["renderer_implemented"]:
            results.append({"artifact":key,"status":"excluded_by_owner","reason":figure["next_action"]});continue
        command=["reproduce.py","--figure",key,"--dataset",dataset,"--output-dir",output/key,"--dpi",args.dpi]
        if key in cycle_ids:command += ["--analysis-dir",analysis]
        if key=="activity_distribution":command += ["--workers",args.workers]
        if key=="representative_sensor_traces" and args.allow_mixed_participants:command += ["--allow-mixed-participants"]
        if key in {"activity_over_time","device_usage_over_time"}:
            if not args.aggregates_dir:
                results.append({"artifact":key,"status":"missing_calendar_aggregates","reason":"No linked dates are reconstructed from public metadata"});continue
            command += ["--aggregates-dir",Path(args.aggregates_dir).resolve()]
            if args.allow_review_only:command += ["--allow-review-only"]
        execute(key,command)
    for table in ("device_sessions","participant_visits","dataset_structure"):
        execute("table_"+table,["tables/tab_"+table+".py","--dataset",dataset,"--output-dir",output/("table_"+table)])
    results.extend({"artifact":key,"status":"excluded_by_owner","reason":"Leave curated manuscript table unchanged for now"}
                   for key in ("hardware_specifications","participant_demographics"))
    write_json(output/"batch_report.json",{"artifacts":results,"dataset_modified":False,"manuscript_modified":False})
    return int(any(r["status"]=="failed" for r in results))


if __name__=="__main__":sys.exit(main())
