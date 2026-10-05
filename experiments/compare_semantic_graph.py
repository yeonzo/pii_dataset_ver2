"""Bounded live comparison on the same six domain/subtype slots as the baseline smoke.

Only the graph policy and per-document relation range are varied through flags.
The production 1-8 stages, model routing, reviewer gates, and output contract run
unchanged. The report contains counts and reason codes, not generated text/values.
"""
from __future__ import annotations

import argparse
import collections
import json

from relation_pipeline.common import DOMAINS, ROOT, atomic_json, load_config
from relation_pipeline.runner import Runner
from relation_pipeline.stages.stage00_prepare import prepare


CASES = (
    ("career_education", "recommendation"),
    ("contract", "service"),
    ("financial", "fraud_report"),
    ("legal", "mediation_application"),
    ("medical", "registration"),
    ("support", "refund_request"),
)
BASELINE = ROOT / "runs" / "smoke_acceptance_20261004_v1" / "statistics" / "smoke_report.json"


def concise(store, cfg):
    candidates = []
    for c in store.rows("SELECT candidate_id,domain,subtype,status,final_stage,reasons FROM candidates ORDER BY candidate_id"):
        attempts = store.rows("SELECT stage,status,reasons FROM stage_attempts WHERE candidate_id=? ORDER BY id",(c["candidate_id"],))
        reviews = store.rows("SELECT overall,consistency,fluency,suitability,response_valid,semantic_passed FROM reviews WHERE candidate_id=? ORDER BY id",(c["candidate_id"],))
        review_codes = sorted({i["code"] for a in attempts if a["stage"] == 7 and a["status"] == "failed" for i in json.loads(a["reasons"])})
        candidates.append({"candidate_id":c["candidate_id"],"domain":c["domain"],"subtype":c["subtype"],
            "status":c["status"],"final_stage":c["final_stage"],
            "final_reason_codes":sorted({i["code"] for i in json.loads(c["reasons"])}),
            "review_reason_codes":review_codes,"reviews":reviews,
            "stages": [{"stage":a["stage"],"status":a["status"],
                        "reason_codes":sorted({i["code"] for i in json.loads(a["reasons"])})} for a in attempts]})
    calls = store.rows("SELECT task,status,estimated_cost_usd FROM api_calls")
    code_counts = collections.Counter(code for c in candidates for code in c["review_reason_codes"])
    accepted = sum(c["status"] == "accepted" for c in candidates)
    baseline = json.load(BASELINE.open()) if BASELINE.is_file() else None
    return {"run_id":cfg["run_id"],"graph_policy":cfg["graph_policy"],"relation_count_range":cfg["relation_count_range"],
        "max_required_per_document":cfg["relation_coverage"]["max_required_per_document"],
        "candidate_count":len(candidates),"accepted":accepted,"acceptance_rate":accepted/len(candidates) if candidates else None,
        "reviewed_candidates":sum(bool(c["reviews"]) for c in candidates),
        "requests":len(calls),"estimated_cost_usd":round(sum(c["estimated_cost_usd"] for c in calls),6),
        "review_issue_candidate_counts":dict(code_counts),
        "baseline":{"run_id":baseline["run_id"],"accepted":baseline["accepted"],
                    "candidate_count":baseline["accepted"]+baseline["rejected"],
                    "requests":baseline["request_count"],"estimated_cost_usd":baseline["estimated_cost_usd"]} if baseline else None,
        "candidates":candidates}


def run(args):
    cfg = load_config()
    cfg.update(graph_policy=args.graph_policy,relation_count_range=[args.min_rel,args.max_rel],
               max_candidates_per_slot=1,max_candidates_per_domain=1,
               run_request_budget=args.request_budget,run_cost_budget_usd=args.cost_cap)
    cfg["relation_coverage"] = {**cfg["relation_coverage"],"max_required_per_document":args.required_per_document}
    store = prepare(cfg,args.run_id,list(DOMAINS),target=1,mode="live")
    try:
        if store.rows("SELECT candidate_id FROM candidates"):
            raise RuntimeError("Use a fresh run ID")
        for domain,subtype in CASES:
            store.execute("UPDATE slots SET subtype=? WHERE domain=?",(subtype,domain))
        runner = Runner(store)
        runner.run(max_candidates=args.max_candidates)
        report = concise(store,runner.cfg)
        path = store.run_dir/"statistics"/"semantic_graph_comparison.json"
        atomic_json(path,report)
        print(json.dumps({k:report[k] for k in ("run_id","graph_policy","relation_count_range","candidate_count","accepted","acceptance_rate","reviewed_candidates","requests","estimated_cost_usd","review_issue_candidate_counts","baseline")},ensure_ascii=False),flush=True)
        print("REPORT "+str(path),flush=True)
    finally:
        store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id",required=True)
    parser.add_argument("--graph-policy",choices=("legacy","scenario_v1"),default="scenario_v1")
    parser.add_argument("--min-rel",type=int,default=4)
    parser.add_argument("--max-rel",type=int,default=6)
    parser.add_argument("--required-per-document",type=int,default=1)
    parser.add_argument("--max-candidates",type=int,default=6)
    parser.add_argument("--request-budget",type=int,default=42)
    parser.add_argument("--cost-cap",type=float,default=.8)
    run(parser.parse_args())
