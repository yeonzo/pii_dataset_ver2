"""Repair two frozen conflicting plans and check supply without generating text."""
from __future__ import annotations

import argparse
from pathlib import Path

from experiments.compare_generation import register
from relation_pipeline.common import StageFailure, atomic_json, digest, load_config, read_json
from relation_pipeline.runner import Runner
from relation_pipeline.stages.stage00_prepare import prepare
from relation_pipeline.stages.stage02_plan import make_plan
from relation_pipeline.value_constraints import value_group_issues


def run(run_id):
    cfg = load_config()
    cfg.update(run_request_budget=4,run_cost_budget_usd=.1,max_provider_requests_per_candidate=2)
    store = prepare(cfg,run_id,domains=["support","financial","legal","medical","contract","career_education"],target=1)
    runner = Runner(store)
    report = {"run_id":run_id,"cases":[],"mode":"live","scope":"Constraint repair and value supply only; no document quality claim."}
    for domain in ("legal","contract"):
        slot = store.rows("SELECT * FROM slots WHERE domain=?",(domain,))[0]
        candidate = slot["slot_id"]+"_c001"
        source = Path("runs/live_paired_prepared_20261003_whole/candidates")/candidate
        plan,condition = read_json(source/"plan.json"),read_json(source/"condition.json")
        condition["run_id"] = runner.cfg["run_id"]
        feedback = [i.json() for i in value_group_issues(plan)]
        assert feedback
        register(store,slot)
        runner.stage(candidate,1,{"frozen_condition":condition},lambda:condition)
        case = {"domain":domain,"candidate_id":candidate,"before_issues":feedback,"repaired_and_value_supply":False}
        try:
            repaired = runner.stage(candidate,2,{"existing_plan":plan,"feedback":feedback},
                lambda:make_plan(runner.client,condition,feedback,plan))
            store.save_artifact(candidate,"plan.json",repaired)
            runner.run_candidate(slot,candidate,1,stop_after=3)
            case["after_issues"] = [i.json() for i in value_group_issues(repaired)]
            case["repaired_and_value_supply"] = (store.run_dir/"candidates"/candidate/"value_map.json").exists()
            case["graph_preserved"] = digest(plan["relations"]) == digest(repaired["relations"])
        except StageFailure as exc:
            case["after_issues"] = [i.json() for i in exc.issues]
            store.finish_candidate(candidate,"rejected",2,case["after_issues"])
        report["cases"].append(case)
        atomic_json(store.run_dir/"value_constraint_repair.json",report)
        print(domain,case["repaired_and_value_supply"],case["after_issues"],flush=True)
    store.manifest()
    report["calls"] = store.rows("SELECT task,model,status,estimated_cost_usd FROM api_calls")
    atomic_json(store.run_dir/"value_constraint_repair.json",report)
    print("REPORT",store.run_dir/"value_constraint_repair.json",flush=True)
    store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id",required=True)
    run(parser.parse_args().run_id)
