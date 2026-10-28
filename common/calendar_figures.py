"""Calendar renderers accept only separate aggregate inputs, never linked dates."""

import csv
import json
from pathlib import Path

import numpy as np

from .activities import write_csv
from .artifacts import manifest,new_output
from .metadata import FAMILIES,ROOT,digest,load_public_metadata
from .plotting import palette,pyplot,save


def configure(parser):
    parser.add_argument("--aggregates-dir",help="Separately reviewed aggregate CSVs and calendar_review.json; no record-to-date crosswalk")
    parser.add_argument("--allow-review-only",action="store_true",help="Explicitly render unapproved aggregates locally for owner review; not permission to publish")
    parser.add_argument("--dpi",type=int,default=180)


def read_aggregates(dataset,directory,allow_review_only):
    root,_,_=load_public_metadata(dataset)
    directory=Path(directory).resolve()
    info=json.loads((directory/"calendar_review.json").read_text(encoding="utf-8"))
    if info.get("schema_version")!="calendar_aggregate_1.0":
        raise ValueError("Unsupported calendar aggregate schema")
    approved=info.get("release_approved") is True
    if not approved and not allow_review_only:
        raise ValueError("Calendar aggregates are review-only; require --allow-review-only for local review, or separately approve before release")
    if info.get("public_metadata_sha256")!=digest(root/"metadata.csv"):
        raise ValueError("Calendar aggregates are from a different public dataset")
    result={}
    schemas={"monthly_device_usage.csv":{"month","family","device","ankle","verified_milliseconds","verified_recordings","native_recordings"},
             "quarterly_activity.csv":{"quarter","family","category","milliseconds","native_recordings"}}
    for name,fields in schemas.items():
        if info["output_hashes"].get(name)!=digest(directory/name):
            raise ValueError("Calendar aggregate checksum mismatch")
        with (directory/name).open(encoding="utf-8",newline="") as f:
            reader=csv.DictReader(f)
            if set(reader.fieldnames or [])!=fields:
                raise ValueError("Unexpected aggregate columns (linked identifiers/dates are not accepted)")
            result[name]=list(reader)
    import re
    for r in result["monthly_device_usage.csv"]:
        if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])",r["month"]) or r["family"] not in FAMILIES:
            raise ValueError("Invalid month/family in calendar aggregates")
        if any(int(r[k])<0 for k in ("verified_milliseconds","verified_recordings","native_recordings")):
            raise ValueError("Negative calendar aggregate")
    for r in result["quarterly_activity.csv"]:
        if not re.fullmatch(r"\d{4}-Q[1-4]",r["quarter"]) or r["family"] not in FAMILIES:
            raise ValueError("Invalid quarter/family in calendar aggregates")
        if any(int(r[k])<0 for k in ("milliseconds","native_recordings")):
            raise ValueError("Negative calendar aggregate")
    monthly_ms=sum(int(r["verified_milliseconds"]) for r in result["monthly_device_usage.csv"])
    quarterly_ms=sum(int(r["milliseconds"]) for r in result["quarterly_activity.csv"])
    if monthly_ms!=quarterly_ms or ("verified_milliseconds" in info and monthly_ms!=info["verified_milliseconds"]):
        raise ValueError("Calendar usage and activity totals do not reconcile")
    return info,result


def smooth_active_curve(values,x):
    """Legacy five-month triangular smoother + nonnegative cubic interpolation."""
    from scipy.interpolate import make_interp_spline
    active=np.flatnonzero(values>0)
    if len(active)<2: return None,None
    s,e=int(active[0]),int(active[-1])+1
    xx,yy=x[s:e],values[s:e]
    if len(yy)>=5:
        kernel=np.asarray([1,2,3,2,1],dtype=float)/9
        yy=np.convolve(yy,kernel,mode="same")
    dense=np.linspace(xx[0],xx[-1],max(260,12*len(xx)))
    smooth=make_interp_spline(xx,yy,k=3)(dense) if len(xx)>=4 else np.interp(dense,xx,yy)
    return dense,np.maximum(smooth,0)


def devices(info,records,output,dpi):
    plt=pyplot()
    months=info["months"]
    x=np.arange(len(months),dtype=float)
    devs=sorted({(r["family"],r["device"]) for r in records},key=lambda p:(FAMILIES.index(p[0]),p[1]))
    ankles=sorted({r["ankle"] for r in records if r["family"] in ("Fox","HK") and r["ankle"]})
    pos={month:i for i,month in enumerate(months)}
    top={d:np.zeros(len(months)) for d in devs};bottom={a:np.zeros(len(months)) for a in ankles}
    native=0
    for r in records:
        j=pos[r["month"]];hours=int(r["verified_milliseconds"])/3600000
        top[(r["family"],r["device"])][j]+=hours
        if r["family"] in ("Fox","HK") and r["ankle"] in bottom: bottom[r["ankle"]][j]+=hours
        native+=int(r["native_recordings"])
    from matplotlib.colors import to_rgb
    colors={}
    for family in FAMILIES:
        dd=[d for d in devs if d[0]==family]
        for d,t in zip(dd,np.linspace(.55,0,len(dd)) if len(dd)>1 else [0]):
            colors[d]=tuple((1-t)*np.asarray(to_rgb(palette()[family]))+t)
    ankle_cmap=plt.get_cmap("tab10")
    fig,(ax,bx)=plt.subplots(2,1,sharex=True,figsize=(19,11),gridspec_kw={"hspace":.03})
    for d,y in top.items():
        ax.bar(x,y,width=.94,alpha=.45,color=colors[d],label=d[1])
        xx,yy=smooth_active_curve(y,x)
        if xx is not None: ax.plot(xx,yy,color=colors[d],lw=2)
    for i,(a,y) in enumerate(bottom.items()):
        color=ankle_cmap(i%10)
        bx.bar(x,-y,width=.94,alpha=.45,color=color,label=a)
        xx,yy=smooth_active_curve(y,x)
        if xx is not None: bx.plot(xx,-yy,color=color,lw=2)
    from matplotlib.ticker import FuncFormatter
    bx.yaxis.set_major_formatter(FuncFormatter(lambda val,pos:f"{abs(val):g}"))
    ax.set_ylabel("Knee device usage [verified h]")
    bx.set_ylabel("Ankle / foot usage [verified h]\nFox and HK pooled")
    ax.set_ylim(bottom=0);bx.set_ylim(top=0)
    for aa in (ax,bx): aa.grid(axis="y",alpha=.2);aa.axhline(0,color="black",lw=.7)
    ticks=[i for i,m in enumerate(months) if m.endswith("-01")]
    bx.set_xticks(ticks,[months[i][:4] for i in ticks]);bx.set_xlim(-.6,len(months)-.4)
    bx.set_xlabel("Recording year (monthly bars; width = one month)")
    ax.legend(loc="upper center",bbox_to_anchor=(.5,1.22),ncol=6,frameon=False,fontsize=10)
    bx.legend(loc="upper center",bbox_to_anchor=(.5,-.15),ncol=max(1,len(ankles)),frameon=False,fontsize=10)
    fig.text(.5,.015,f"{native:,} native-clock recordings retained in the dataset but not assigned hours. Bars overlap by device; smooth curves are visual trends, not additive time estimates.",ha="center",fontsize=10)
    fig.subplots_adjust(top=.85,bottom=.15,left=.07,right=.98)
    return save(fig,output,"all_knee_ankle_devices_monthly_usage",dpi)


def activity(info,records,output,dpi):
    plt=pyplot()
    cats=json.loads((ROOT/"configs/activities.json").read_text())["categories"]
    quarters=info["quarters"];pos={q:i for i,q in enumerate(quarters)}
    values={c["key"]:np.zeros(len(quarters)) for c in cats}
    native=np.zeros(len(quarters),dtype=int)
    for r in records:
        i=pos[r["quarter"]]
        if r["category"] not in values: raise ValueError("Unexpected aggregate category")
        values[r["category"]][i]+=int(r["milliseconds"])/3600000
        # Native counts appear only in the unknown category, never as duration.
        native[i]+=int(r["native_recordings"])
    total=sum(values.values());assigned=sum(values[c["key"]] for c in cats[:9])
    x=np.arange(len(quarters),dtype=float)*.22
    fig,axes=plt.subplots(2,1,sharex=True,figsize=(max(13,len(quarters)*.23),9.5),gridspec_kw={"hspace":.08})
    axes[0].bar(x+.035,total,width=.18,color=".66",alpha=.75,label="All verified recording time",zorder=1)
    bottom=np.zeros(len(x));norm=np.zeros(len(x))
    for c in cats[:9]:
        y=values[c["key"]]
        if not np.any(y): continue
        axes[0].bar(x,y,bottom=bottom,width=.15,color=c["color"],label=c["label"],zorder=2)
        yy=np.divide(y,assigned,out=np.zeros(y.shape),where=assigned>0)*100
        axes[1].bar(x,yy,bottom=norm,width=.15,color=c["color"],zorder=2)
        bottom+=y;norm+=yy
    for j,(full,part) in enumerate(zip(total,assigned)):
        gap=full-part
        if gap>1e-9:
            annotation=f"U:{gap:.1f} h" if gap>=.05 else "U:<0.1 h"
            axes[0].text(x[j]+.035,full+.04,annotation,rotation=90,ha="center",va="bottom",fontsize=10)
    years=sorted({q[:4] for q in quarters})
    for year in years:
        idx=[j for j,q in enumerate(quarters) if q[:4]==year]
        first=idx[0]
        for aa in axes: aa.axvline(x[first]-.11,color=".3",lw=.7,alpha=.6)
        axes[0].text((x[first]+x[idx[-1]])/2,1.025,f"{year}\n{total[idx].sum():.1f} h",transform=axes[0].get_xaxis_transform(),ha="center",va="bottom",fontsize=10)
    known=np.flatnonzero(assigned>0)
    if len(known):
        boundary=x[known[0]]-.11
        for aa in axes:
            aa.axvline(boundary,color="black",ls="--",lw=1.1)
    axes[0].set_ylim(0,max(float(total.max())*1.35,1))
    axes[0].set_ylabel("Recorded time [verified h]")
    axes[1].set_ylabel("Assigned activity time [%]");axes[1].set_ylim(0,100)
    ticks=[i for i,q in enumerate(quarters) if q.endswith("Q1")]
    axes[1].set_xticks(x[ticks],[quarters[i][:4] for i in ticks])
    axes[1].set_xlim(x[0]-.13,x[-1]+.18)
    axes[1].set_xlabel("Recording year (four fixed calendar quarters per year)")
    for aa in axes: aa.grid(axis="y",alpha=.2,zorder=0)
    handles,labels=axes[0].get_legend_handles_labels()
    fig.legend(handles,labels,loc="lower center",ncol=5,frameon=False,bbox_to_anchor=(.5,.035),fontsize=10)
    fig.text(.5,.012,f"U: unknown/outside assigned 1X-9X time. {native.sum():,} native-clock files have unknown duration and are excluded from hours. Lower panel is conditional on assigned time.",ha="center",fontsize=9)
    fig.subplots_adjust(left=.08,right=.99,top=.86,bottom=.19)
    write_csv(Path(output)/"quarterly_totals.csv",[{"quarter":q,"verified_hours":float(total[j]),"assigned_hours":float(assigned[j]),
              "unknown_outside_hours":float(total[j]-assigned[j]),"native_files_without_duration":int(native[j])} for j,q in enumerate(quarters)])
    return save(fig,output,"sm_event_label_3month_stacked_combined",dpi)


def run(figure,args):
    if not args.aggregates_dir: raise ValueError("--aggregates-dir is required")
    info,records=read_aggregates(args.dataset,args.aggregates_dir,args.allow_review_only)
    output=new_output(args.dataset,args.output_dir)
    files=devices(info,records["monthly_device_usage.csv"],output,args.dpi) if figure=="device_usage_over_time" else activity(info,records["quarterly_activity.csv"],output,args.dpi)
    (output/"REVIEW_STATUS.md").write_text("# Calendar aggregate review\n\nRelease approved: "+str(info["release_approved"])+". These outputs inherit the input review status. They contain aggregates only, with no participant, visit, record IDs or source paths. This does not guarantee anonymity or authorize publication. Native-clock files are counted but excluded from time. Exact source-support milliseconds are used; no struct.time elapsed-duration assumption.\n",encoding="utf-8")
    manifest(output,figure,{**info["output_hashes"],"calendar_review.json":digest(Path(args.aggregates_dir)/"calendar_review.json")},
             {"allow_review_only":args.allow_review_only,"dpi":args.dpi},extra={"release_approved":info["release_approved"],"figures":files})
    print(json.dumps({"figure":figure,"release_approved":info["release_approved"],"files":files},indent=2))
