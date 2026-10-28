"""Shared shades and zero-aligned family axes, ported from the gait/current grids."""

import json
from pathlib import Path

import numpy as np

from .metadata import FAMILIES, ROOT


def pyplot():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.family":"DejaVu Sans","font.size":12,"svg.fonttype":"none"})
    return plt


def palette():
    return json.loads((ROOT/"configs/style.json").read_text())["family_colors"]


def shades(configs):
    from matplotlib.colors import to_rgb
    colors = {}
    for family in FAMILIES:
        indices = [k for k,c in enumerate(configs) if c["family"] == family]
        for k,t in zip(indices,np.linspace(.52,0,len(indices)) if len(indices)>1 else [0]):
            colors[k] = tuple((1-t)*np.asarray(to_rgb(palette()[family]))+t)
    return colors


def zero_aligned_limits(profiles, configs):
    """profiles = [configuration, column, position, signal], like legacy means."""
    result = {}
    for j in range(profiles.shape[-1]):
        bounds = {}
        for family in FAMILIES:
            idx = [k for k,c in enumerate(configs) if c["family"] == family]
            vals = profiles[idx,...,j]
            finite = vals[np.isfinite(vals)]
            if not len(finite):
                continue
            low,high = float(finite.min()),float(finite.max())
            pad = .06*(high-low) if high>low else .05*max(abs(low),1)
            bounds[family] = (low-pad,high+pad)
        if not bounds:
            continue
        lo,hi = min(0,*[v[0] for v in bounds.values()]),max(0,*[v[1] for v in bounds.values()])
        p = float(np.clip(-lo/(hi-lo),.05,.95)) if lo < 0 < hi else (.08 if lo>=0 else .92)
        for family,(low,high) in bounds.items():
            span = max(-low/p,high/(1-p),1e-6)
            result[(j,family)] = (-p*span,(1-p)*span)
    return result


def family_axes(base, column, last_column, row, limits):
    """All colored tick axes on the right of the last column only."""
    # twinx() changes the base axis's tick side; finish creating twins first.
    axes = {family:base if i==0 else base.twinx() for i,family in enumerate(FAMILIES)}
    guide_limit = next((limit for (r,_),limit in limits.items() if r==row),(-1,1))
    for i,family in enumerate(FAMILIES):
        ax = axes[family]
        ax.set_ylim(*limits.get((row,family),guide_limit))
        ax.patch.set_visible(False)
        for spine in ax.spines.values():
            spine.set_visible(False)
        ax.tick_params(axis="y",left=False,right=False,labelleft=False,labelright=False)
        if column == last_column and (row,family) in limits:
            ax.spines["right"].set_visible(True)
            ax.spines["right"].set_position(("outward",i*49))
            ax.spines["right"].set_color(palette()[family])
            ax.yaxis.set_ticks_position("right")
            ax.tick_params(axis="y",right=True,labelright=True,colors=palette()[family],labelsize=10)
            from matplotlib.ticker import MaxNLocator
            ax.yaxis.set_major_locator(MaxNLocator(4))
            if row == 0:
                ax.text(1+i*.27,1.07,family,color=palette()[family],transform=ax.transAxes,
                        ha="left",va="bottom",fontsize=10,fontweight="bold")
    base.axhline(0,color=".65",lw=.55,zorder=0)
    base.grid(axis="x",alpha=.14)
    return axes


def save(fig,output,name,dpi=180):
    paths = []
    for ext in ("png","svg"):
        path = Path(output)/(name+"."+ext)
        fig.savefig(path,dpi=dpi,bbox_inches="tight")
        paths.append(path.name)
    pyplot().close(fig)
    return paths


def finite_mean(values,axis=0):
    count = np.isfinite(values).sum(axis=axis)
    return np.divide(np.nansum(values,axis=axis),count,out=np.full(count.shape,np.nan),where=count>0)


def mean_std(total,square,n):
    mean = np.divide(total,n,out=np.full(total.shape,np.nan),where=n>0)
    variance = np.divide(square,n,out=np.full(square.shape,np.nan),where=n>0)-mean**2
    return mean,np.sqrt(np.maximum(variance,0))
