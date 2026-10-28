#!/usr/bin/env python3
"""Three-cycle same-participant sensor overlay with one global shift per family."""
import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from common.cli import figure_entrypoint


def configure(parser):
    parser.add_argument("--analysis-dir",help="Shared cycle analysis")
    parser.add_argument("--participant",help="Optional retained TF pseudonym; otherwise choose a common participant deterministically")
    parser.add_argument("--allow-mixed-participants",action="store_true",help="Explicit alternative if no four-family common participant has eligible labeled cycles")
    parser.add_argument("--candidate-recordings",type=int,default=12,help="Per-family ranked recording shortlist; all valid windows in these files are compared")
    parser.add_argument("--dpi",type=int,default=180)


def corr(a,b):
    import numpy as np
    if len(a)<2 or len(b)<2:
        return None
    aa=np.interp(np.linspace(0,1,100),np.linspace(0,1,len(a)),a)
    bb=np.interp(np.linspace(0,1,100),np.linspace(0,1,len(b)),b)
    if not np.all(np.isfinite(aa)) or not np.all(np.isfinite(bb)) or np.std(aa)<1e-12 or np.std(bb)<1e-12:
        return None
    return float(np.corrcoef(aa,bb)[0,1])


def best_shift(reference,target,max_shift):
    """Signed Pearson on raw-time overlap, bounded to avoid tiny-overlap maxima."""
    import numpy as np
    best=(float("-inf"),0)
    for lag in range(-max_shift,max_shift+1):
        left,right=max(0,lag),min(len(reference),len(target)+lag)
        if right-left < max(12,.5*min(len(reference),len(target))):
            continue
        a,b=reference[left:right],target[left-lag:right-lag]
        if not np.all(np.isfinite(a)) or not np.all(np.isfinite(b)) or np.std(a)<1e-12 or np.std(b)<1e-12:
            continue
        r=float(np.corrcoef(a,b)[0,1])
        # Prefer smaller shift for equivalent scores.
        if r>best[0]+1e-12 or (abs(r-best[0])<1e-12 and abs(lag)<abs(best[1])):
            best=(r,lag)
    return best[1],best[0] if np.isfinite(best[0]) else None


def run(args):
    import numpy as np
    from common.activities import write_csv
    from common.artifacts import manifest,new_output,write_json
    from common.cycles import SENSORS,load_analysis
    from common.cycle_figures import LABELS
    from common.metadata import FAMILIES,digest,load_public_metadata
    from common.plotting import palette,pyplot,save,zero_aligned_limits,family_axes
    from common.recordings import public_checksums,read_named_columns
    if not args.analysis_dir or args.candidate_recordings<1:
        raise ValueError("--analysis-dir and positive --candidate-recordings are required")
    info,_=load_analysis(args.dataset,args.analysis_dir)
    root,_,rows=load_public_metadata(args.dataset)
    byid={int(r["record_id"]):r for r in rows}
    expected=public_checksums(root)
    cycles=defaultdict(list)
    with (Path(args.analysis_dir)/"cycle_inventory.csv").open(encoding="utf-8") as f:
        for c in csv.DictReader(f):
            if c["accepted"]=="True" and c["decade"]=="2" and c["left_boundary"]=="anchor" and c["right_boundary"]=="anchor" and c["signal_eligibility"][2]=="1":
                cycles[int(c["record_id"])].append((int(c["start"]),int(c["end"])))
    windows={}
    for rid,cc in cycles.items():
        cc.sort()
        triples=[cc[i:i+3] for i in range(len(cc)-2) if cc[i][1]==cc[i+1][0] and cc[i+1][1]==cc[i+2][0]]
        if triples:
            windows[rid]=triples
    coverage=defaultdict(set)
    for rid in windows:
        p=byid[rid]["participant_id"]
        if p: coverage[p].add(byid[rid]["family"])
    common=sorted(p for p,ff in coverage.items() if set(ff)==set(FAMILIES))
    participant=args.participant or (common[0] if common else None)
    mixed = not participant or participant not in common
    if mixed and (args.participant or not args.allow_mixed_participants):
        raise ValueError("No four-family common participant with three consecutive eligible 2X segments; do not silently mix participants. Available: "+", ".join(common))
    shortlist={}
    for family in FAMILIES:
        ranked=sorted((rid for rid in windows if byid[rid]["family"]==family and (mixed or byid[rid]["participant_id"]==participant)),
                      key=lambda rid:(0 if family=="HK" and byid[rid]["device_code"]=="HK-1.3" else 1,-len(windows[rid]),rid))
        shortlist[family]=ranked[:args.candidate_recordings]
    arrays={}
    cols=("sample_index","time_s",*SENSORS,*(s+"_valid" for s in SENSORS))
    for rr in shortlist.values():
        for rid in rr:
            values,_=read_named_columns(root,byid[rid],cols,expected[byid[rid]["csv_path"]])
            values[:,2:10]=np.where(values[:,10:18]==1,values[:,2:10],np.nan)
            arrays[rid]=values
    ref_id=shortlist["HK"][0]
    # First choose the most duration-consistent reference triple, not the first three steps.
    ref_window=min(windows[ref_id],key=lambda w:(np.std([e-s for s,e in w]),w[0][0]))
    ref=arrays[ref_id][ref_window[2][0]:ref_window[2][1],4]
    selections={"HK":(ref_id,ref_window,1.0)}
    for family in FAMILIES:
        if family=="HK": continue
        best=None
        for rid in shortlist[family]:
            for w in windows[rid]:
                rs=[corr(ref,arrays[rid][s:e,4]) for s,e in w]
                if any(r is None for r in rs): continue
                score=float(np.mean(rs))
                candidate=(score,-rid,-w[0][0],rid,w)
                if best is None or candidate[:3]>best[:3]: best=candidate
        if best is None: raise ValueError("No nonconstant eligible knee-angle candidate for "+family)
        selections[family]=(best[3],best[4],best[0])
    transforms={}
    for family,(rid,w,score) in selections.items():
        target=arrays[rid][w[2][0]:w[2][1],4]
        lag,r=(0,1.0) if family=="HK" else best_shift(ref,target,max(1,int(.5*min(len(ref),len(target)))))
        # Original relative recording samples remain contiguous; no cycle concatenation/time warp.
        shift=(ref_window[2][0]-ref_window[0][0]-w[2][0]+lag)/100
        transforms[family]={"record_id":rid,"participant_id":byid[rid]["participant_id"],"family":family,"configuration":byid[rid]["configuration_code"],
            "selected_cycles":w,"template_mean_r":score,"third_cycle_shift_samples":lag,"third_cycle_overlap_r":r,
            "record_time_shift_s":shift,"original_csv_sha256":expected[byid[rid]["csv_path"]]}
    start=0.;end=(ref_window[-1][1]-ref_window[0][0])/100
    # Use extra context from the original files so shifts never create artificial edge truncation.
    start=max(start,*[t["record_time_shift_s"] for t in transforms.values()])
    end=min(end,*[(len(arrays[t["record_id"]])-1)/100+t["record_time_shift_s"] for t in transforms.values()])
    if end<=start: raise ValueError("No common continuous post-shift overlap")
    display={}
    profiles=np.full((4,1,max(len(v) for v in arrays.values()),8),np.nan)
    configs=[]
    for k,family in enumerate(FAMILIES):
        t=transforms[family];values=arrays[t["record_id"]]
        x=values[:,1]+t["record_time_shift_s"]
        mask=(x>=start)&(x<=end)
        display[family]=(x[mask],values[mask,2:10])
        configs.append({"family":family,"code":t["configuration"]})
        for j in range(8):
            yy=values[mask,j+2]
            if len(yy): profiles[k,0,:len(yy),j]=yy
    limits=zero_aligned_limits(profiles,configs)
    output=new_output(root,args.output_dir)
    plt=pyplot();fig,axes=plt.subplots(8,1,figsize=(15,24),sharex=True)
    for j,(ax,label) in enumerate(zip(axes,LABELS)):
        aa=family_axes(ax,0,0,j,limits)
        for family,(x,ys) in display.items():
            aa[family].plot(x,ys[:,j],color=palette()[family],lw=1.4,label=family)
        for s,_ in ref_window:
            boundary=(s-ref_window[0][0])/100
            if start<=boundary<=end: ax.axvline(boundary,color=".4",ls="--",lw=.8)
        ax.set_ylabel(label+"\n(source units)")
        ax.set_xlim(start,end)
    axes[-1].set_xlabel("Relative time after alignment [s]")
    from matplotlib.lines import Line2D
    legend_labels=[f+" ("+transforms[f]["participant_id"]+")" for f in FAMILIES]
    fig.legend([Line2D([],[],color=palette()[f],lw=2) for f in FAMILIES],legend_labels,ncol=4,loc="lower center",frameon=False)
    if mixed:
        fig.suptitle("Representative walking: mixed-participant visualization",fontsize=15)
    fig.subplots_adjust(left=.12,right=.79,top=.96,bottom=.05,hspace=.24)
    files=save(fig,output,"daq_aligned_representative_2x_cycles_sensor_overlay_3steps",args.dpi)
    write_json(output/"representative_selections.json",{"participant":participant,"mixed_participants":mixed,"common_participants_available":common,"reference_family":"HK",
               "candidate_recordings_per_family":{f:len(v) for f,v in shortlist.items()},"selections":transforms,
               "common_display_window_s":[start,end],"alignment":"One global temporal translation per family estimated on the third selected cycle knee angle; no amplitude normalization, cycle time warp or sign changes. Extra original-file context fills shifted edges. Reference markers denote HK cycle boundaries, not simultaneous measured heel strikes across devices."})
    numerical=[]
    for family,(x,ys) in display.items():
        for xx,yy in zip(x,ys):
            numerical.append({"family":family,"aligned_time_s":float(xx),**{s:float(v) if np.isfinite(v) else None for s,v in zip(SENSORS,yy)}})
    write_csv(output/"representative_traces.csv",numerical)
    (output/"methods.md").write_text("# Representative overlay\n\n"+("Explicit mixed-participant alternative: no common four-family participant meets the eligible labeled-cycle criteria. Participant IDs are disclosed in the legend/selection ledger; not a within-participant comparison. " if mixed else "One common participant. ")+"Three consecutive eligible 2X segments per selected recording. All eligible triples in a deterministic recording shortlist are compared by knee-angle shape. A single translation per family is estimated on the third selected cycle. Original continuous recording data, including context outside the selected triples, are displayed over the common post-shift window; no concatenation, temporal warping, amplitude calibration or new sign changes. Dashed markers indicate reference-HK cycle starts only. This is a visualization selection, not an unbiased comparison or simultaneous trials. Public 100 Hz signals are used, not original 1 kHz traces. Missing channels remain missing.\n",encoding="utf-8")
    manifest(output,"representative_sensor_traces",{**info["input_hashes"],"shared_analysis":digest(Path(args.analysis_dir)/"execution_manifest.json")},
             {"participant":participant,"candidate_recordings":args.candidate_recordings,"dpi":args.dpi},extra={"figures":files})
    print(json.dumps({"participant":participant,"selected_record_ids":{f:t["record_id"] for f,t in transforms.items()},"files":files},indent=2))


def main(argv=None):
    return figure_entrypoint("representative_sensor_traces",argv,runner=run,configure=configure)


if __name__=="__main__":
    sys.exit(main())
