"""Repair four frozen failed drafts within a cap; never regenerate a document."""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from experiments.compare_generation import register, summarize
from relation_pipeline.common import ROOT, atomic_json, digest, file_hash, load_config, now, read_json
from relation_pipeline.repair_tasks import actual_entities
from relation_pipeline.runner import Runner
from relation_pipeline.schemas import PLAN
from relation_pipeline.statistics import export
from relation_pipeline.stages.stage00_prepare import prepare
from relation_pipeline.stages.stage02_plan import check_plan

DOMAINS = ["support","financial","legal","medical","contract","career_education"]


def run(run_id, source, max_repairs=2):
    cfg = load_config()
    # The draft call already happened in the frozen source run; count only new repairs.
    cfg.update(max_document_actions=max_repairs,run_request_budget=24,run_cost_budget_usd=1.,
               max_provider_requests_per_candidate=6,max_candidates_per_slot=1,max_candidates_per_domain=1)
    store = prepare(cfg,run_id,DOMAINS,target=1)
    if store.rows("SELECT candidate_id FROM candidates"):
        raise RuntimeError("Use a fresh run ID")
    runner = Runner(store)
    report = {"started_at":now(),"source_run":str(source.resolve()),"generation_model":cfg["generation_model"],
        "review_model":cfg["review_model"],"new_generation_calls_allowed":0,"repair_calls_per_case":1,
        "plan_and_values_frozen":True,"cases":[],"skipped_before_generation":[],
        "code_hashes":{n:file_hash(ROOT/"relation_pipeline"/n) for n in ("repair_tasks.py","runner.py","value_constraints.py")}}
    path = store.run_dir/"targeted_repair_comparison.json"
    for domain in DOMAINS:
        slot = store.rows("SELECT * FROM slots WHERE domain=?",(domain,))[0]
        candidate = slot["slot_id"]+"_c001"
        directory = source/"candidates"/candidate
        if not (directory/"draft_versions/draft_v1.json").exists():
            report["skipped_before_generation"].append({"domain":domain,"candidate_id":candidate})
            continue
        condition = read_json(directory/"condition.json")
        condition["run_id"] = runner.cfg["run_id"]
        assert condition["subtype"] == slot["subtype"]
        plan = read_json(directory/"plan.json")
        check_plan({key:plan[key] for key in PLAN["properties"]},condition)
        values = read_json(directory/"value_map.json")
        draft = read_json(directory/"draft_versions/draft_v1.json")
        register(store,slot)
        runner.stage(candidate,1,{"config_hash":runner.cfg["config_hash"],"slot":{k:slot[k] for k in ("slot_id","domain","subtype")},"ordinal":1},lambda c=condition:c)
        store.save_artifact(candidate,"plan.json",plan)
        runner.stage(candidate,2,{"frozen_plan_hash":digest(plan)},lambda p=plan:p)
        runner.run_candidate(slot,candidate,1,stop_after=3)
        assert read_json(store.run_dir/"candidates"/candidate/"value_map.json") == values
        runner.stage(candidate,4,{"shared_draft_hash":digest(draft),"source":str(directory)},lambda d=draft:d,name="stage_04_shared_draft.json")
        store.save_artifact(candidate,"draft_versions/draft_v1.json",draft)
        store.save_artifact(candidate,"state.json",{"draft":draft,"revision":1,"shared_draft_hash":digest(draft)})
        store.execute("UPDATE candidates SET status='running',finished_at=NULL WHERE candidate_id=?",(candidate,))
        print(f"REPAIR {candidate}",flush=True)
        runner.run_candidate(slot,candidate,1)
        outcome = summarize(store,candidate)
        versions = sorted((store.run_dir/"candidates"/candidate/"draft_versions").glob("draft_v*.json"),key=lambda p:int(p.stem.split('_v')[1]))
        node_total = len(plan["entities"])
        outcome["missing_entity_tokens_before"] = node_total-len(actual_entities(draft,plan))
        outcome["missing_entity_tokens_after"] = node_total-len(actual_entities(read_json(versions[-1]),plan))
        outcome["progress"] = [read_json(p) for p in sorted((store.run_dir/"candidates"/candidate/"repairs").glob("progress_*.json"))]
        outcome["source_draft_hash"] = digest(draft)
        report["cases"].append(outcome)
        print(f"RESULT {candidate} {outcome['status']} stage={outcome['final_stage']} missing={outcome['missing_entity_tokens_before']}->{outcome['missing_entity_tokens_after']} reasons={[i['code'] for i in outcome['reasons']]}",flush=True)
        store.manifest()
        export(store,runner.cfg)
        atomic_json(path,report)
    cases = report["cases"]
    calls = [c for case in cases for c in case["calls"]]
    assert not any(c["task"] in ("draft","plan") for c in calls)
    report.update(finished_at=now(),totals={"evaluated":len(cases),"accepted":sum(c["status"]=="accepted" for c in cases),
        "reached_review":sum(bool(c["grades"]) for c in cases),"calls_by_task":dict(Counter(c["task"] for c in calls)),
        "missing_entities_before":sum(c["missing_entity_tokens_before"] for c in cases),
        "missing_entities_after":sum(c["missing_entity_tokens_after"] for c in cases),
        "all_code_checks_passed_after_repair":sum(any(p["all_code_checks_passed"] for p in c["progress"]) for c in cases),
        "estimated_cost_usd":sum(c["estimated_cost_usd"] for c in calls)})
    atomic_json(path,report)
    print(report["totals"],flush=True)
    print(f"REPORT {path}",flush=True)
    store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id",required=True)
    parser.add_argument("--source",type=Path,default=Path("runs/live_paired_prepared_20261003_whole"))
    parser.add_argument("--max-repairs",type=int,choices=(1,2),default=2)
    args = parser.parse_args()
    run(args.run_id,args.source,args.max_repairs)
