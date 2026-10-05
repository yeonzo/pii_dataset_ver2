"""Retest all eligible paired cases after fixing cross-batch entity remention.

Reuse every original baseline result; never sample/select a more favorable baseline.
"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from experiments.compare_generation import DOMAINS, register, summarize
from experiments.split_generation import SplitClient
from relation_pipeline.client import Client
from relation_pipeline.common import ROOT, atomic_json, digest, file_hash, load_config, now, read_json
from relation_pipeline.prompt_inputs import condition_input
from relation_pipeline.runner import Runner
from relation_pipeline.statistics import export
from relation_pipeline.store import Store
from relation_pipeline.stages.stage00_prepare import prepare


def totals(outcomes):
    calls = [c for o in outcomes for c in o["calls"] if c["task"] != "plan"]
    return {"evaluated":len(outcomes),"accepted":sum(o["status"] == "accepted" for o in outcomes),
        "reached_review":sum(bool(o["grades"]) for o in outcomes),
        "calls_by_task":dict(Counter(c["task"] for c in calls)),
        "generation_review_cost_usd":sum(c["estimated_cost_usd"] for c in calls),
        "initial_issues":dict(Counter(code for o in outcomes for code,n in (o["diagnoses"][0]["issue_counts"].items() if o["diagnoses"] else []) for _ in range(n))),
        "final_reject_codes":dict(Counter(i["code"] for o in outcomes for i in o["reasons"]))}


def run(prefix, baseline_dir):
    baseline = Store(baseline_dir)
    cfg = load_config()
    cfg.update(max_candidates_per_slot=1,max_candidates_per_domain=1,run_request_budget=32,
               run_cost_budget_usd=1.0,max_document_actions=3)
    store = prepare(cfg,prefix+"_split",DOMAINS,target=1)
    if store.rows("SELECT candidate_id FROM candidates"):
        raise RuntimeError("Use a fresh prefix")
    runner = Runner(store)
    runner._client = SplitClient(Client(runner.cfg,store))
    report = {"started_at":now(),"sample_design":"all eligible original baseline cases, no baseline resampling",
        "baseline_directory":str(baseline_dir.resolve()),"generation_model":cfg["generation_model"],
        "review_model":cfg["review_model"],"initial_total_max_output_tokens":cfg["max_output_tokens"]["draft"],
        "repair_opportunities_per_arm":1,"production_defaults_changed":False,
        "change_from_first_pilot":"permit every planned entity token/ref target in each batch, preserving natural remention",
        "experiment_source_hashes":{n:file_hash(ROOT/"experiments"/n) for n in ("split_generation.py","retest_split.py")},
        "pairs":[],"shared_preparation_failures":[],"totals":{}}
    report_path = ROOT/"runs"/(prefix+"_comparison.json")
    cases = []
    for domain in DOMAINS:
        source_slot = baseline.rows("SELECT * FROM slots WHERE domain=?",(domain,))[0]
        slot = store.rows("SELECT * FROM slots WHERE domain=?",(domain,))[0]
        candidate = slot["slot_id"]+"_c001"
        directory = baseline_dir/"candidates"/candidate
        if not (directory/"value_map.json").exists():
            report["shared_preparation_failures"].append(summarize(baseline,candidate))
            continue
        outcome = summarize(baseline,candidate)
        if outcome["status"] not in ("accepted","rejected"):
            raise RuntimeError("Wait for every original baseline case to finish")
        condition = read_json(directory/"condition.json")
        split_condition = {**condition,"run_id":runner.cfg["run_id"]}
        plan = read_json(directory/"plan.json")
        values = read_json(directory/"value_map.json")
        assert source_slot["subtype"] == slot["subtype"]
        assert register(store,slot) == candidate
        stage1 = {"config_hash":runner.cfg["config_hash"],"slot":{k:slot[k] for k in ("slot_id","domain","subtype")},"ordinal":1}
        runner.stage(candidate,1,stage1,lambda c=split_condition:c)
        store.save_artifact(candidate,"plan.json",plan)
        runner.stage(candidate,2,{"shared_plan_hash":digest(plan)},lambda p=plan:p)
        runner.run_candidate(slot,candidate,1,stop_after=3)
        assert read_json(store.run_dir/"candidates"/candidate/"value_map.json") == values
        assert condition_input(condition) == condition_input(split_condition)
        cases.append((candidate,slot,condition,plan,values,outcome))
    for candidate,slot,condition,plan,values,outcome in cases:
        pair = {"candidate_id":candidate,"domain":condition["domain"],"subtype":condition["subtype"],
                "layout_variant":condition["layout_variant"],"length_target":condition["length_target"],
                "min_chars":condition["min_chars"],"relation_count":len(plan["relations"]),
                "privacy_counts":dict(Counter(r["target_privacy"] for r in plan["relations"])),
                "plan_hash":digest(plan),"value_map_hash":digest(values),"arms":{"whole":outcome}}
        print(f"RETEST {candidate} split",flush=True)
        store.execute("UPDATE candidates SET status='running',finished_at=NULL WHERE candidate_id=?",(candidate,))
        runner.run_candidate(slot,candidate,1)
        split_outcome = summarize(store,candidate)
        pair["arms"]["split"] = split_outcome
        print(f"RESULT {candidate} {split_outcome['status']} stage={split_outcome['final_stage']} reasons={[i['code'] for i in split_outcome['reasons']]}",flush=True)
        report["pairs"].append(pair)
        store.manifest()
        export(store,runner.cfg)
        atomic_json(report_path,report)
    report["finished_at"] = now()
    for arm in ("whole","split"):
        report["totals"][arm] = totals([p["arms"][arm] for p in report["pairs"]])
    atomic_json(report_path,report)
    print(f"REPORT {report_path}",flush=True)
    print(report["totals"],flush=True)
    store.close()
    baseline.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix",required=True)
    parser.add_argument("--baseline-from",required=True,type=Path)
    args = parser.parse_args()
    run(args.prefix,args.baseline_from)
