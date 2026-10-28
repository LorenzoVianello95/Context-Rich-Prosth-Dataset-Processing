#!/usr/bin/env python3
"""Participant visits on the approved relative-time axis, colored by family."""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from common.cli import figure_entrypoint
from common.metadata import FAMILIES, digest, load_public_metadata


def configure(parser):
    parser.add_argument("--dpi",type=int,default=180)


def run(args):
    from common.activities import write_csv
    from common.artifacts import manifest,new_output
    from common.plotting import pyplot,palette,save
    root,_,rows=load_public_metadata(args.dataset)
    output=new_output(root,args.output_dir)
    plt=pyplot()
    visits=defaultdict(set)
    people=sorted({r["participant_id"] for r in rows if r["participant_id"]})
    for r in rows:
        if r["visit_id"]:
            visits[r["participant_id"]].add((int(r["elapsed_visit_days"]),r["visit_id"],r["family"]))
    numerical=[]
    fig,ax=plt.subplots(figsize=(14,max(6,.34*len(people))))
    for y,p in enumerate(people):
        vv=sorted(visits[p])
        if not vv:
            ax.text(0,y,"Visit timing unavailable",fontsize=9,va="center")
            continue
        days=[v[0] for v in vv]
        ax.plot([min(days),max(days)],[y,y],color="black",lw=.55,zorder=1)
        # Small vertical offsets expose simultaneous family observations, not timing shifts.
        for day,vid,f in vv:
            offset=(FAMILIES.index(f)-1.5)*.10
            ax.scatter(day,y+offset,s=39,color=palette()[f],edgecolors="white",linewidths=.25,zorder=3)
            numerical.append({"participant_id":p,"visit_id":vid,"elapsed_visit_days":day,"family":f})
    ax.set_yticks(range(len(people)),people)
    ax.invert_yaxis()
    ax.set_xlabel("Elapsed days since each participant's first observed visit")
    ax.set_ylabel("Participant")
    ax.grid(axis="x",alpha=.2)
    for f in FAMILIES:
        ax.scatter([],[],s=40,color=palette()[f],label=f)
    ax.legend(loc="lower center",bbox_to_anchor=(.5,-.09),ncol=4,frameon=False)
    fig.tight_layout()
    files=save(fig,output,"subject_leg_adoption_timeline_relative",args.dpi)
    write_csv(output/"subject_visits_relative.csv",numerical)
    (output/"methods.md").write_text("# Relative participant timeline\n\nOne dot per distinct public participant/visit/family group. Black lines span observed relative visit days, not continuous use or follow-up without gaps. Small vertical family offsets expose same-day overlaps; no horizontal shifts. Alphabetical participant order. All metadata records, including native-clock files, contribute visit groups; no clock-derived durations are assigned. No calendar dates are reconstructed.\n",encoding="utf-8")
    manifest(output,"subject_timeline",{"metadata.csv":digest(root/"metadata.csv"),"DATASET_CONTENT.json":digest(root/"DATASET_CONTENT.json")},
             {"dpi":args.dpi},extra={"participants":len(people),"participant_visit_family_groups":len(numerical),"figures":files})
    print(f"Timeline: {len(people)} participants, {len(numerical)} visit/family groups")


def main(argv=None):
    return figure_entrypoint("subject_timeline",argv,runner=run,configure=configure)


if __name__=="__main__":
    sys.exit(main())
