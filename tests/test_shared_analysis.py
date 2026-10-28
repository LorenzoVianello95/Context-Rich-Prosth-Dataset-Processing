"""Cycle boundaries, masks, current signs, zero axes and aggregate privacy gates."""
import csv
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from common.calendar_figures import read_aggregates
from common.cycles import CURRENTS,PARAMETERS,SENSORS,STATES,analyze_record,choose_anchor,fz_segments,normalized_cycle,regular_segments,state_runs
from common.metadata import SCHEMA,digest
from common.plotting import family_axes,pyplot,zero_aligned_limits
from figures.fig_representative_sensor_traces import best_shift
from tables.paper_tables import sessions,structure


class SharedAnalysisTests(unittest.TestCase):
    def test_run_boundaries_do_not_require_all_four_phases(self):
        labels=np.repeat([61,62,61,64,11],3)
        runs=state_runs(labels)
        segments=regular_segments(runs,STATES[6],61)
        self.assertEqual([(c[0],c[1]) for c in segments],[(0,6),(6,12)])
        self.assertEqual(segments[0][2],(61,62))
        self.assertEqual(segments[0][3],"group_or_file_entry")
        self.assertEqual(segments[1][4],"group_exit")

    def test_no_file_boundary_concatenation(self):
        a=regular_segments(state_runs(np.repeat([21,22],5)),STATES[2],21)
        b=regular_segments(state_runs(np.repeat([23,24,21],5)),STATES[2],21)
        self.assertNotIn((21,22,23,24),[c[2] for c in a+b])

    def test_anchors_use_entry_counts_and_passive_fallback(self):
        from collections import Counter
        self.assertEqual(choose_anchor(Counter({61:2,62:20}),STATES[6],6),62)
        self.assertEqual(choose_anchor(Counter({71:50,72:25,73:25}),STATES[7],7),71)
        self.assertIsNone(choose_anchor(Counter(),STATES[7],7))

    def test_normalize_once_and_never_bridge_missing_values(self):
        values=np.column_stack((np.arange(9),np.arange(9)))
        valid=np.ones(values.shape);valid[3,1]=0
        norm,eligible=normalized_cycle(values,valid,n=100)
        np.testing.assert_array_equal(eligible,[True,False])
        self.assertTrue(np.all(np.isnan(norm[:,1])))
        self.assertEqual(norm[0,0],0);self.assertEqual(norm[-1,0],8)

    def test_every_upcrossing_in_start_state_and_duration_conversion(self):
        labels=np.full(200,61)
        fz=np.tile(np.r_[np.zeros(25),np.ones(25)],4)
        seg,threshold,smooth,minlen=fz_segments(labels,fz,STATES[6],61,.01,.5)
        self.assertEqual(threshold,.5)
        self.assertAlmostEqual(smooth,.21);self.assertAlmostEqual(minlen,.10)
        self.assertEqual(sum(s[4]=="fz_crossing" for s in seg),4)
        # The same waveform does not split when the crossing is in a different state.
        no,_t,_s,_m=fz_segments(np.full(200,62),fz,STATES[6],61,.01,.5)
        self.assertEqual(len(no),1)
        missing,*_=fz_segments(labels,np.full(200,np.nan),STATES[6],61,.01)
        self.assertEqual(missing,[])
        missing,*_=fz_segments(labels,np.full(200,np.nan),STATES[6],61,.01,.5)
        self.assertEqual(missing,[])

    def test_current_zero_exclusion_is_ankle_only_and_sign_not_reapplied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);n=40
            s=root/"s.csv";c=root/"c.csv"
            header=("sample_index","time_s",*SENSORS,*(x+"_valid" for x in SENSORS),*PARAMETERS,"state_labels")
            data=np.column_stack((np.arange(n),np.arange(n)/100,np.ones((n,8)),np.ones((n,8)),np.ones((n,6)),np.repeat([21,22,23,24],10)))
            with s.open("w",newline="") as f:
                writer=csv.writer(f);writer.writerow(header);writer.writerows(data)
            with c.open("w",newline="") as f:
                writer=csv.writer(f);writer.writerow(("sample_index","time_s",*CURRENTS,*(x+"_valid" for x in CURRENTS)))
                writer.writerows(np.column_stack((np.arange(n),np.arange(n)/100,-np.ones(n)*2,np.zeros(n),np.ones((n,2)))))
            row={"record_id":"1","rows":str(n),"csv_path":"s.csv","current_csv_path":"c.csv","status":"accepted","duration_verified":"1","sampling_rate_hz":"100","verified_grid_duration_s":".4"}
            cycle={"accepted":True,"start":0,"end":40,"decade":2}
            _,groups,_,_,inventory,_,_=analyze_record((root,row,digest(s),digest(c),[cycle]))
            np.testing.assert_array_equal(groups[2][0][:,8],-2)
            self.assertTrue(np.all(groups[2][2][:,8]==1))
            self.assertTrue(np.all(groups[2][2][:,9]==0))
            self.assertTrue(inventory[0]["all_zero_ankle_current_excluded"])

    def test_axes_share_zero_but_not_scale_and_all_ticks_are_right(self):
        configs=[{"family":"Fox"},{"family":"HK"}]
        values=np.asarray([[[[-2],[3]]],[[[-20],[60]]]])
        limits=zero_aligned_limits(values,configs)
        p=[-lo/(hi-lo) for lo,hi in limits.values()]
        self.assertAlmostEqual(p[0],p[1])
        self.assertNotEqual(limits[(0,"Fox")],limits[(0,"HK")])
        plt=pyplot();fig,ax=plt.subplots()
        aa=family_axes(ax,0,0,0,limits)
        self.assertEqual(aa["Fox"].yaxis.get_ticks_position(),"right")
        self.assertEqual(aa["HK"].yaxis.get_ticks_position(),"right")
        plt.close(fig)
        fig,ax=plt.subplots()
        sparse={(0,"HK"):(-2,8)}
        aa=family_axes(ax,0,0,0,sparse)
        self.assertEqual(aa["Fox"].get_ylim(),aa["HK"].get_ylim())
        plt.close(fig)

    def test_shift_direction_and_minimum_overlap(self):
        ref=np.sin(np.linspace(0,7,100))+.3*np.cos(np.linspace(0,13,100))
        target=np.r_[np.zeros(7),ref[:-7]]
        lag,r=best_shift(ref,target,20)
        self.assertEqual(lag,-7);self.assertGreater(r,.99)

    def test_calendar_review_gate_and_linked_column_rejection(self):
        from test_foundation import fixture
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixture(root/"data");(root/"agg").mkdir()
            usage=root/"agg/monthly_device_usage.csv";activity=root/"agg/quarterly_activity.csv"
            usage.write_text("month,family,device,ankle,verified_milliseconds,verified_recordings,native_recordings\n2025-01,HK,HK-1.3,tf,1000,1,0\n")
            activity.write_text("quarter,family,category,milliseconds,native_recordings\n2025-Q1,HK,2X,1000,0\n")
            info={"schema_version":"calendar_aggregate_1.0","release_approved":False,"public_metadata_sha256":digest(root/"data/metadata.csv"),
                  "output_hashes":{p.name:digest(p) for p in (usage,activity)}}
            path=root/"agg/calendar_review.json";path.write_text(json.dumps(info))
            with self.assertRaisesRegex(ValueError,"review-only"):read_aggregates(root/"data",root/"agg",False)
            read_aggregates(root/"data",root/"agg",True)
            usage.write_text(usage.read_text().replace("native_recordings","native_recordings,participant_id"))
            info["output_hashes"][usage.name]=digest(usage);path.write_text(json.dumps(info))
            with self.assertRaisesRegex(ValueError,"Unexpected aggregate columns"):read_aggregates(root/"data",root/"agg",True)

    def test_metadata_tables_have_totals_and_continuous_structure(self):
        from test_foundation import fixture
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);rows=fixture(root/"data");(root/"out").mkdir()
            sessions(rows,root/"out");structure(rows,root/"out")
            self.assertIn("Total sessions: 2",(root/"out/tab_legs.tex").read_text())
            text=(root/"out/tab_dataset_structure.tex").read_text()
            self.assertIn("No sliding windows",text)
            self.assertIn("Unverified native clock",text)


if __name__=="__main__":unittest.main()
