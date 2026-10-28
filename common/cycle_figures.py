"""Render reviewed gait/current/parameter/amplitude/count layouts from one analysis."""

import csv
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from .activities import write_csv
from .artifacts import manifest, new_output, write_json
from .cycles import CURRENTS, PARAMETERS, SENSORS, STATES, load_analysis
from .metadata import FAMILIES, digest
from .plotting import family_axes, finite_mean, mean_std, palette, pyplot, save, shades, zero_aligned_limits

ACTIVITIES = ("Walking (2X / 7X)","Stair ascent (3X)","Stair descent (4X)","Ramp ascent (5X)","Ramp descent (6X)")
DISPLAY_GROUPS = ((0,5),(1,),(2,),(3,),(4,))
LABELS = ("Fz","My","Knee angle","Knee velocity","Ankle angle","Ankle velocity","Thigh angle","Shank angle")
PARAM_LABELS = ("Knee stiffness","Knee damping","Knee equilibrium angle","Ankle stiffness","Ankle damping","Ankle equilibrium angle")


def configure(parser):
    parser.add_argument("--analysis-dir",required=False,help="Shared analysis built by python -m common.cycles; required to render")
    parser.add_argument("--dpi",type=int,default=180)


def series_grid(info,data,output,current=False,dpi=180,only_family=None):
    plt = pyplot()
    configs,colors = info["configurations"],shades(info["configurations"])
    mean,_ = mean_std(data["total"],data["square"],data["n"])
    sl = slice(8,10) if current else slice(0,8)
    profiles = mean[...,sl]
    limits = zero_aligned_limits(profiles,configs)
    labels = ("Knee actual current","Ankle actual current") if current else LABELS
    fig,base = plt.subplots(len(labels),5,figsize=(21,11 if current else 4.0*len(labels)),squeeze=False,sharex=True)
    handles = {}
    x = np.linspace(0,100,100)
    for row,label in enumerate(labels):
        for col,indices in enumerate(DISPLAY_GROUPS):
            ax = base[row,col]
            aa = family_axes(ax,col,4,row,limits)
            for k,config in enumerate(configs):
                if only_family and config["family"] != only_family:
                    continue
                for group in indices:
                    y = profiles[k,group,:,row]
                    if not np.any(np.isfinite(y)):
                        continue
                    line, = aa[config["family"]].plot(x,y,color=colors[k],lw=1.5,alpha=.95,
                                                     linestyle="--" if group==5 else "-")
                    handles[config["code"]] = line
            ax.set_xlim(0,100)
            if row == 0:
                ax.set_title(ACTIVITIES[col],fontsize=13,pad=27)
            if row == len(labels)-1:
                ax.set_xlabel("Gait cycle [%]")
            if col == 0:
                ax.set_ylabel(label+"\n(source units)",labelpad=12)
    fig.legend(list(handles.values()),list(handles),loc="lower center",ncol=5,frameon=False,
               bbox_to_anchor=(.48,.008),fontsize=10)
    fig.subplots_adjust(left=.07,right=.84,top=.94,bottom=.25 if current else .08,hspace=.24,wspace=.12)
    name = "current_indices_all_sublegs_by_activity_mean" if current else "gait_phase_grid_by_leg"
    if only_family:
        name += "_"+only_family
    files = save(fig,output,name,dpi)
    write_json(Path(output)/(name+"_axes.json"),{f"{row}:{family}":list(v) for (row,family),v in limits.items()})
    return files


def heatmaps(info,analysis,output,dpi=180):
    import matplotlib.colors as colors
    plt = pyplot()
    records = list(csv.DictReader((Path(analysis)/"cycle_counts.csv").open(encoding="utf-8")))
    groups = defaultdict(lambda:np.zeros(5,dtype=np.int64))
    detailed = defaultdict(lambda:np.zeros(5,dtype=np.int64))
    families = defaultdict(lambda:np.zeros(5,dtype=np.int64))
    for r in records:
        d = int(r["decade"])
        j = 0 if d in (2,7) else d-2
        n = int(r["sensor_contributing_cycles"])
        family,code = r["family"],r["configuration"]
        key = code.split("+")[0] if family in ("HK","Fox") else code
        groups[(family,key)][j] += n
        detailed[(family,code)][j] += n
        families[(family,family)][j] += n
    files=[]
    for name,source in (("gait_phase_step_count_heatmap_sublegs",detailed),
                        ("gait_phase_step_count_heatmap_sublegs_hl_fox_grouped_by_knee",groups),
                        ("gait_phase_step_count_heatmap_legs",families)):
        keys = sorted(source,key=lambda k:(FAMILIES.index(k[0]),k[1]))
        counts = np.column_stack([source[k] for k in keys])
        denominator = counts.sum(axis=1,keepdims=True)
        fractions = np.divide(counts,denominator,out=np.zeros(counts.shape),where=denominator>0)
        vmax = float(fractions.max()) if fractions.size and fractions.max()>0 else 1
        # Same physical cell size, including the four-family-only figure.
        # Explicit inch geometry keeps the four-family cells the same size as sublegs.
        width=2.2+.64*len(keys)+1.15
        height=2.4+.64*5+.5
        fig=plt.figure(figsize=(width,height))
        ax=fig.add_axes([2.2/width,2.4/height,.64*len(keys)/width,.64*5/height])
        im=ax.imshow(fractions,cmap="viridis",vmin=0,vmax=vmax,aspect="auto")
        ax.set_xticks(np.arange(len(keys)),[k[1] for k in keys],rotation=90,fontsize=10)
        ax.set_yticks(range(5),["Walking (2X/7X)","Stair ascent","Stair descent","Ramp ascent","Ramp descent"])
        for j in range(1,len(keys)):
            if keys[j][0] != keys[j-1][0]:
                ax.axvline(j-.5,color="white",lw=2.5)
        for (r,c),number in np.ndenumerate(counts):
            red,green,blue,_=im.cmap(im.norm(fractions[r,c]))
            ink="black" if .2126*red+.7152*green+.0722*blue>.55 else "white"
            ax.text(c,r,f"{number:,}",ha="center",va="center",color=ink,fontsize=9,fontweight="bold")
        cax=fig.add_axes([(2.2+.64*len(keys)+.18)/width,2.4/height,.13/width,.64*5/height])
        fig.colorbar(im,cax=cax,label="Share within activity (colors only)")
        files+=save(fig,output,name,dpi)
        write_csv(Path(output)/(name+".csv"),[{"activity":ACTIVITIES[r],"family":family,"configuration":code,
                   "steps":int(counts[r,c]),"color_fraction":float(fractions[r,c])} for c,(family,code) in enumerate(keys) for r in range(5)])
    return files


def amplitudes(info,data,output,dpi=180):
    plt=pyplot()
    configs=info["configurations"]
    a=data["amplitude"]
    fig,axes=plt.subplots(2,1,figsize=(max(12,.58*len(configs)),12),sharex=True)
    numerical=[]
    for ax,index,title in zip(axes,(0,3),("Median within-cycle peak-to-peak range","Median within-cycle mean")):
        values=a[:,index,:].T
        finite=values[np.isfinite(values)]
        lo,hi=(float(finite.min()),float(finite.max())) if len(finite) else (0,1)
        if lo==hi: hi=lo+1
        image=ax.imshow(np.ma.masked_invalid(values),cmap="viridis",vmin=lo,vmax=hi,aspect="auto")
        ax.set_yticks(range(8),LABELS)
        ax.set_title(title+" (uncalibrated source units)",fontsize=14)
        for (r,c),v in np.ndenumerate(values):
            color="black"
            if np.isfinite(v):
                red,green,blue,_=image.cmap(image.norm(v))
                color="black" if .2126*red+.7152*green+.0722*blue>.55 else "white"
            if not np.isfinite(v):
                annotation="nan"
            elif v!=0 and abs(v)<.01:
                annotation=f"{v:.0e}".replace("e-0","e-").replace("e+0","e+")
            else:
                annotation=f"{v:.3g}"
            ax.text(c,r,annotation,ha="center",va="center",fontsize=8.5,color=color)
            numerical.append({"family":configs[c]["family"],"configuration":configs[c]["code"],"sensor":SENSORS[r],
                              "metric":"peak_to_peak" if index==0 else "cycle_mean",
                              "median":float(v) if np.isfinite(v) else None,
                              "p10":float(a[c,index+1,r]) if np.isfinite(a[c,index+1,r]) else None,
                              "p90":float(a[c,index+2,r]) if np.isfinite(a[c,index+2,r]) else None})
        fig.colorbar(image,ax=ax,fraction=.02,pad=.015)
    axes[-1].set_xticks(range(len(configs)),[c["code"] for c in configs],rotation=90,fontsize=10)
    fig.tight_layout()
    write_csv(Path(output)/"sensor_amplitude_by_device_2x7x.csv",numerical)
    return save(fig,output,"sensor_amplitude_by_device_2x7x",dpi)


def controller(info,data,output,dpi=180):
    plt=pyplot()
    configs=info["configurations"]
    means,stds=mean_std(data["phase_total"],data["phase_square"],data["phase_n"])
    order=(2,7,3,4,5,6)
    states=[[s for s in STATES[d] if np.any(data["phase_n"][:,s]>0)] for d in order]
    use=[(d,ss) for d,ss in zip(order,states) if ss]
    # Bounds include error bars and use the same per-family range across columns.
    extremes=np.concatenate((means-stds,means+stds),axis=1)[:,None,:,:]
    limits=zero_aligned_limits(extremes,configs)
    colors=shades(configs)
    fig,base=plt.subplots(6,len(use),figsize=(23,25),squeeze=False)
    handles,metrics,numerical={},[],[]
    for r,label in enumerate(PARAM_LABELS):
        for col,(decade,ss) in enumerate(use):
            ax=base[r,col]
            aa=family_axes(ax,col,len(use)-1,r,limits)
            x=np.arange(len(ss))
            profiles={}
            for k,config in enumerate(configs):
                y,sd=means[k,ss,r],stds[k,ss,r]
                if not np.any(np.isfinite(y)):
                    continue
                line=aa[config["family"]].errorbar(x,y,yerr=sd,fmt="o-",lw=1.2,ms=3,capsize=2,color=colors[k])
                handles[config["code"]]=line[0]
                for j,s in enumerate(ss):
                    numerical.append({"configuration":config["code"],"family":config["family"],"parameter":PARAMETERS[r],"state":s,
                        "run_count":int(data["phase_n"][k,s,r]),"mean":float(y[j]) if np.isfinite(y[j]) else None,
                        "std":float(sd[j]) if np.isfinite(sd[j]) else None})
            for family in FAMILIES:
                kk=[k for k,c in enumerate(configs) if c["family"]==family]
                profiles[family]=finite_mean(means[kk][:,ss,r],axis=0)
            rr=[]
            for i,f1 in enumerate(FAMILIES):
                for f2 in FAMILIES[i+1:]:
                    a,b=profiles[f1],profiles[f2]
                    good=np.isfinite(a)&np.isfinite(b)
                    corr=None
                    if good.sum()>=2 and np.std(a[good])>1e-12 and np.std(b[good])>1e-12:
                        corr=float(np.corrcoef(a[good],b[good])[0,1]); rr.append(corr)
                    metrics.append({"parameter":PARAMETERS[r],"decade":decade,"family_a":f1,"family_b":f2,
                                    "common_states":int(good.sum()),"signed_pearson_r":corr})
            ax.text(.03,.97,"mean r="+(f"{np.mean(rr):.2f}" if rr else "n/a"),transform=ax.transAxes,va="top",fontsize=10,
                    bbox={"facecolor":"white","alpha":.8,"edgecolor":"none"})
            ax.set_xticks(x,[str(s) for s in ss] if r==5 else [""]*len(ss))
            if r==0: ax.set_title(f"{decade}X",pad=27,fontsize=15)
            if r==5: ax.set_xlabel("State label")
            if col==0: ax.set_ylabel(label+"\n(source units)")
    fig.legend(list(handles.values()),list(handles),loc="lower center",ncol=5,frameon=False,bbox_to_anchor=(.49,.005),fontsize=10)
    fig.subplots_adjust(left=.08,right=.85,top=.95,bottom=.095,wspace=.15,hspace=.2)
    write_csv(Path(output)/"controller_parameter_phase_means.csv",numerical)
    write_csv(Path(output)/"controller_parameter_similarity.csv",metrics)
    return save(fig,output,"sm_dof_act_phase_means_grid_all_devices",dpi)


def run(figure,args):
    if not args.analysis_dir:
        raise ValueError("--analysis-dir is required; first build python -m common.cycles --dataset ... --output-dir ...")
    if args.dpi<1:
        raise ValueError("dpi must be positive")
    info,data=load_analysis(args.dataset,args.analysis_dir)
    output=new_output(args.dataset,args.output_dir)
    if figure=="gait_sensor_grid":
        files=series_grid(info,data,output,dpi=args.dpi)
        for family in FAMILIES:
            files+=series_grid(info,data,output,dpi=args.dpi,only_family=family)
    elif figure=="currents_by_activity":
        files=series_grid(info,data,output,current=True,dpi=args.dpi)
    elif figure=="step_counts":
        files=heatmaps(info,args.analysis_dir,output,args.dpi)
    elif figure=="sensor_amplitude":
        files=amplitudes(info,data,output,args.dpi)
    elif figure=="controller_parameters":
        files=controller(info,data,output,args.dpi)
    else:
        raise ValueError("Unknown shared-analysis figure")
    (output/"methods.md").write_text("# "+figure+"\n\n"+"\n\n".join(info["methods"].values())+
        "\n\nColors encode device families; shades encode standardized configurations. Family y-ranges are shared across activity columns and their zeros aligned. Display scales are not calibration factors. Gait/current traces are mean-only. 7X walking curves are dashed and overlaid, not concatenated with 2X.\n",encoding="utf-8")
    manifest(output,figure,{**info["input_hashes"],"shared_analysis":digest(Path(args.analysis_dir)/"execution_manifest.json")},
             {"dpi":args.dpi},extra={"figures":files,"verified_recordings":info["verified_recordings"],"accepted_segments":info["accepted_segments"]})
    print(json.dumps({"figure":figure,"files":files},indent=2))
