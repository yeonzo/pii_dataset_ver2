"""Bounded production-path pilot for final coverage, privacy and participant roles.

Two fresh documents; one initial draft and at most two patches per document.
No weakened acceptance checks. Results describe this pilot, not a success-rate estimate.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter

from relation_pipeline.common import ROOT, StageFailure, atomic_json, load_config, now, read_json
from relation_pipeline.runner import Runner
from relation_pipeline.statistics import export
from relation_pipeline.stages.stage00_prepare import prepare


def run(run_id, offline=False, domain=None):
    cfg = load_config()
    cfg.update(run_request_budget=14,run_cost_budget_usd=.5,max_candidates_per_slot=1)
    cases = [(d,s) for d,s in (("financial","wire_transfer"),("support","support_ticket")) if domain is None or domain == d]
    cfg["run_request_budget"] = 7*len(cases)
    store = prepare(cfg,run_id,[d for d,_ in cases],target=1,mode="offline" if offline else "live")
    try:
        if store.rows("SELECT * FROM candidates"):
            raise RuntimeError("Use a fresh run ID")
        runner = Runner(store)
        if offline:
            from relation_pipeline.offline import OfflineClient
            runner._client = OfflineClient(runner.cfg,store)
        report = {"started_at":now(),"mode":runner.cfg["mode"],"cases":[],
            "limits":{"max_candidates":len(cases),"max_requests":7*len(cases),"max_cost_usd":.5,"max_initial_drafts_per_document":1,"max_patches_per_document":2},
            "source_hashes":runner.cfg["resource_hashes"],
            "note":"Fresh pilot with unchanged production acceptance; not a paired comparison or quality benchmark when offline."}
        path = store.run_dir/"semantic_policy_report.json"
        for domain, subtype in cases:
            slot = store.rows("SELECT * FROM slots WHERE domain=?",(domain,))[0]
            store.execute("UPDATE slots SET subtype=? WHERE slot_id=?",(subtype,slot["slot_id"]))
            slot["subtype"] = subtype
            store.event(None,0,"pilot_subtype_selected",{"slot_id":slot["slot_id"],"subtype":subtype})
            candidate = slot["slot_id"]+"_c001"
            store.execute("INSERT INTO candidates(candidate_id,slot_id,domain,subtype,created_at) VALUES(?,?,?,?,?)",
                (candidate,slot["slot_id"],domain,subtype,now()))
            print("START "+candidate,flush=True)
            fatal = False
            try:
                runner.run_candidate(slot,candidate,1)
            except StageFailure as exc:
                fatal = exc.fatal
            row = store.rows("SELECT candidate_id,domain,subtype,status,final_stage,reasons FROM candidates WHERE candidate_id=?",(candidate,))[0]
            row["reasons"] = json.loads(row["reasons"])
            root = store.run_dir/"candidates"/candidate
            condition = read_json(root/"condition.json")
            row.update(n_parties=condition["n_parties"],person_slots=condition["person_slots"],required_relation_types=condition["required_relation_types"],
                calls=store.rows("SELECT task,model,status,input_tokens,output_tokens,estimated_cost_usd FROM api_calls WHERE candidate_id=?",(candidate,)),
                grades=store.rows("SELECT overall,consistency,fluency,suitability,response_valid,semantic_passed FROM reviews WHERE candidate_id=?",(candidate,)),
                reviews=[read_json(p) for p in sorted((root/"review_versions").glob("review_v*.json"))],
                repair_progress=[read_json(p) for p in sorted((root/"repairs").glob("progress_*.json"))])
            report["cases"].append(row)
            store.manifest()
            stats = export(store,runner.cfg)
            calls = [c for case in report["cases"] for c in case["calls"]]
            report.update(totals={"evaluated":len(report["cases"]),"accepted":sum(case["status"] == "accepted" for case in report["cases"]),
                "calls_by_task":dict(Counter(c["task"] for c in calls)),"estimated_cost_usd":sum(c["estimated_cost_usd"] for c in calls)},
                relation_coverage=stats["relation_coverage"],completion=stats["completion"])
            atomic_json(path,report)
            print(f"RESULT {candidate} {row['status']} stage={row['final_stage']} reasons={[i['code'] for i in row['reasons']]}",flush=True)
            if fatal:
                break
        report["finished_at"] = now()
        atomic_json(path,report)
        print(json.dumps(report["totals"],ensure_ascii=False),flush=True)
        print("REPORT "+str(path),flush=True)
    finally:
        store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id",required=True)
    parser.add_argument("--offline",action="store_true")
    parser.add_argument("--domain",choices=("financial","support"))
    args = parser.parse_args()
    run(args.run_id,args.offline,args.domain)
