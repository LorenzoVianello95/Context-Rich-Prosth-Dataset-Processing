"""Public-metadata manuscript table ports; curated clinical/hardware tables excluded."""

import argparse
import json
from pathlib import Path

from common.activities import write_csv
from common.artifacts import manifest,new_output
from common.metadata import FAMILIES,digest,load_public_metadata
from tables.reproduce_metadata_tables import compute_tables,tex,write_tex


def sessions(rows,output):
    variants,coverage,_=compute_tables(rows)
    blocks={f:[r for r in variants if r["family"]==f] for f in FAMILIES}
    totals={r["family"]:r["source_sessions"] for r in coverage}
    lines=[r"\begin{table}[ht]",r"\centering",r"\scriptsize",r"\setlength{\tabcolsep}{2.5pt}",r"\begin{tabular}{@{}lr|lr|lr|lr@{}}",r"\hline",
           " & ".join(r"\multicolumn{2}{c"+("|" if i<3 else "")+r"}{\textbf{"+f+r"}}" for i,f in enumerate(FAMILIES))+r" \\",r"\hline",
           " & ".join([r"Variant & $n$"]*4)+r" \\",r"\hline"]
    for j in range(max(map(len,blocks.values()))):
        cells=[]
        for f in FAMILIES:
            r=blocks[f][j] if j<len(blocks[f]) else None
            cells.extend((tex(r["configuration_code"]),str(r["source_sessions"])) if r else ("--","--"))
        lines.append(" & ".join(cells)+r" \\")
    lines += [r"\hline"," & ".join(r"\textbf{Total} & \textbf{"+str(totals[f])+"}" for f in FAMILIES)+r" \\",r"\hline",
              r"\multicolumn{8}{c}{\textbf{Total sessions: "+str(sum(totals.values()))+r"}} \\",r"\hline",r"\end{tabular}",
              r"\caption{Session counts ($n$) by standardized device configuration. Sessions are unique neutral source-folder identifiers, not unique visit days. Calendar recording periods are deliberately omitted because the public metadata contains relative timing only.}",
              r"\label{tab:variant-sessions-four-columns-thin}",r"\end{table}"]
    (output/"tab_legs.tex").write_text("\n".join(lines)+"\n",encoding="utf-8")
    write_csv(output/"tab_legs.csv",variants)


def participants(rows,output):
    _,_,all_people=compute_tables(rows)
    top=sorted(all_people,key=lambda r:(-r["unique_visit_groups"],r["participant_id"]))[:25]
    write_tex(output/"tab_participant_visits.tex",["Participant","Visit groups","Source sessions"],
              [[r["participant_id"],r["unique_visit_groups"],r["source_sessions"]] for r in top],
              "Top 25 participants by distinct observed visit groups. Source folders are reported separately from visits. Full counts are provided in the accompanying CSV and full table.",
              "tab:users_number_of_visits")
    write_tex(output/"tab_participant_devices.tex",["Participant",*FAMILIES,"Unique visits"],
              [[r["participant_id"],*[r[f+"_visit_groups"] for f in FAMILIES],r["unique_visit_groups"]] for r in all_people],
              "Distinct public visit groups per participant and family. A shared visit can include multiple families, so family counts are not additive.",
              "tab:users_number_of_legs")
    write_tex(output/"tab_participant_visits_full.tex",["Participant","Visit groups","Source sessions"],
              [[r["participant_id"],r["unique_visit_groups"],r["source_sessions"]] for r in all_people],
              "Complete participant visit and source-folder counts. Participants without a known visit group are not assigned one.","tab:participant-visits-full")
    write_csv(output/"participant_visits_full.csv",all_people)
    write_csv(output/"participant_visits_top25.csv",top)


def structure(rows,output):
    values=[
        ("metadata.csv","One row per recording; public IDs, configuration, relative visits, masks/provenance and table paths","N/A"),
        ("recordings/<family>/<id>.csv","Continuous eight sensors, six controller parameters, decoded labels, estimated phase and masks","100 Hz verified grid"),
        ("currents/<family>/<id>.csv","Aligned knee/ankle actual current, original channel values and masks; join by sample index","100 Hz verified grid"),
        ("annotations/<family>/<id>_pvd.csv.gz","Original PVD annotation arrays; independent row grid, not 100 Hz","Original row grid"),
        ("timing_quarantine/<family>/<id>.csv.gz","Preserved native-clock sensor/parameter recordings; no certified duration","Unverified native clock"),
        ("native_currents/<family>/<id>.csv.gz","Current companion for native-clock exceptions","Unverified native clock"),
        ("records.jsonl","Recording-level table schemas, mapping decisions and clock evidence","N/A"),
        ("DATASET_CONTENT.json / .md","Machine/human-readable content and processing description","N/A"),
        ("checksums.sha256","SHA-256 index for dataset integrity verification","N/A")]
    write_tex(output/"tab_dataset_structure.tex",["File pattern","Content","Sampling"],values,
              "Continuous recording-level CSV release structure. Values are in uncalibrated source units. No sliding windows are imposed. Native-clock exceptions are separate and not assigned 100 Hz or verified hours. Original annotations require the supplied alignment/provenance; do not join by row number.",
              "tab:continuous-csv-structure")
    path=output/"tab_dataset_structure.tex"
    path.write_text(path.read_text(encoding="utf-8").replace(r"\begin{tabular}{lll}",
                    r"\begin{tabular}{p{.26\linewidth}p{.48\linewidth}p{.18\linewidth}}"),encoding="utf-8")
    write_csv(output/"tab_dataset_structure.csv",[dict(file_pattern=a,content=b,sampling=c) for a,b,c in values])


def main(kind,argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset",required=True)
    parser.add_argument("--output-dir",required=True)
    args=parser.parse_args(argv)
    try:
        root,_,rows=load_public_metadata(args.dataset)
        output=new_output(root,args.output_dir)
        {"sessions":sessions,"participants":participants,"structure":structure}[kind](rows,output)
        report=manifest(output,"table_"+kind,{name:digest(root/name) for name in ("metadata.csv","DATASET_CONTENT.json")},
                        extra={"recordings":len(rows),"scope":"No clinical demographics, hardware specifications or participant-linked calendar dates used."})
        print(json.dumps({"table":kind,"outputs":list(report["outputs"])},indent=2))
    except (OSError,ValueError) as exc:
        parser.error(str(exc))
