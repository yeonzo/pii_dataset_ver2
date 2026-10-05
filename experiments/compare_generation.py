"""Bounded live paired pilot. Run: python -m experiments.compare_generation --prefix NAME"""
from __future__ import annotations

import argparse
from collections import Counter
from pathlib import Path

from experiments.split_generation import SplitClient
from relation_pipeline.client import Client
from relation_pipeline.common import ROOT, StageFailure, atomic_json, digest, load_config, now, read_json
from relation_pipeline.prompt_inputs import condition_input
from relation_pipeline.schemas import PLAN
from relation_pipeline.runner import Runner
from relation_pipeline.statistics import export
from relation_pipeline.stages.stage00_prepare import prepare
from relation_pipeline.stages.stage02_plan import attach_plan_metadata, check_plan

DOMAINS = ["support","financial","legal","medical","contract","career_education"]


def register(store, slot):
    candidate = slot["slot_id"]+"_c001"
    store.execute("INSERT INTO candidates(candidate_id,slot_id,domain,subtype,created_at) VALUES(?,?,?,?,?)",
                  (candidate,slot["slot_id"],slot["domain"],slot["subtype"],now()))
    return candidate


def summarize(store, candidate):
    row = store.rows("SELECT candidate_id,domain,subtype,status,final_stage,reasons FROM candidates WHERE candidate_id=?",(candidate,))[0]
    import json
    row["reasons"] = json.loads(row["reasons"])
    row["calls"] = store.rows("SELECT task,model,status,input_tokens,output_tokens,estimated_cost_usd FROM api_calls WHERE candidate_id=?",(candidate,))
    row["grades"] = store.rows("SELECT overall,consistency,fluency,suitability,response_valid,semantic_passed,format_passed FROM reviews WHERE candidate_id=?",(candidate,))
    path = store.run_dir/"candidates"/candidate
    row["diagnoses"] = []
    for diagnosis_path in sorted((path/"diagnoses").glob("*.json")):
        data = read_json(diagnosis_path)
        row["diagnoses"].append({"file":diagnosis_path.name,"issue_counts":dict(Counter(i["code"] for i in data["issues"])),
            "issues":data["issues"],"rendered_chars":data["metrics"].get("rendered_chars"),
            "missing_entity_ids":[i["entity_id"] for i in data["issues"] if i["code"] == "MISSING_ENTITY_MENTION"]})
    row["review_checks"] = [read_json(p)["checks"] for p in sorted((path/"review_versions").glob("review_v*.json"))]
    row["assignments"] = [read_json(p) for p in sorted((path/"experiment").glob("assignment_*.json"))]
    row["cost_usd"] = sum(c["estimated_cost_usd"] for c in row["calls"])
    row["artifact_directory"] = str(path)
    return row


def shared_plan(source, candidate, condition):
    """Experimental preparation only: remove unused nodes and constraints referring to them."""
    directory = source/"candidates"/candidate
    if (directory/"plan.json").exists():
        raw = read_json(directory/"plan.json")
        plan = {key:raw[key] for key in PLAN["properties"]}
        check_plan(plan,condition)
        return attach_plan_metadata(plan), {"source":"plan.json","removed_entities":[],"removed_constraints":[]}
    import json
    # Freeze the last completed planner response, rather than choosing by eventual draft success.
    raw_path = sorted((directory/"api").glob("call_*.json"))[-1]
    raw = read_json(raw_path)
    content = "".join(block.get("text","") for item in raw.get("output",[])
                      for block in item.get("content",[]) if block.get("type") == "output_text")
    plan = json.loads(content)
    used = {r[key] for r in plan["relations"] for key in ("source","target")}
    removed = [e["entity_id"] for e in plan["entities"] if e["entity_id"] not in used]
    removed_constraints = [k["constraint_id"] for k in plan["slot_constraints"] if not set(k["entity_ids"]) <= used]
    plan["entities"] = [e for e in plan["entities"] if e["entity_id"] in used]
    plan["slot_constraints"] = [k for k in plan["slot_constraints"] if set(k["entity_ids"]) <= used]
    check_plan(plan,condition)
    return attach_plan_metadata(plan), {"source":str(raw_path),"removed_entities":removed,"removed_constraints":removed_constraints}


def run(prefix, shared_source=None):
    cfg = load_config()
    cfg.update(max_candidates_per_slot=1,max_candidates_per_domain=1,run_request_budget=48,run_cost_budget_usd=1.5)
    stores = {"whole":prepare({**cfg,"max_document_actions":2},prefix+"_whole",DOMAINS,target=1),
              "split":prepare({**cfg,"max_document_actions":3},prefix+"_split",DOMAINS,target=1)}
    if any(store.rows("SELECT candidate_id FROM candidates") for store in stores.values()):
        raise RuntimeError("Use a fresh experiment prefix; no selective reruns of completed cases")
    runners = {"whole":Runner(stores["whole"]),"split":Runner(stores["split"])}
    runners["split"]._client = SplitClient(Client(runners["split"].cfg,stores["split"]))
    report = {"started_at":now(),"sample_design":"one frozen paired case per domain; alternating arm order",
        "shared_plan_calls_charged_to":"whole ledger, excluded from generation cost comparison",
        "generation_model":cfg["generation_model"],"review_model":cfg["review_model"],
        "initial_total_max_output_tokens":cfg["max_output_tokens"]["draft"],"repair_opportunities_per_arm":1,
        "production_defaults_changed":False,"pairs":[],"shared_plan_failures":[],
        "shared_source":str(shared_source) if shared_source else None,
        "shared_preparation":"remove unused nodes/constraints before paired generation" if shared_source else "unchanged planner"}
    report_path = ROOT/"runs"/(prefix+"_comparison.json")
    cases = []
    for domain in DOMAINS:
        slot = stores["whole"].rows("SELECT * FROM slots WHERE domain=?",(domain,))[0]
        candidate = register(stores["whole"],slot)
        print(f"SHARED PLAN {candidate}",flush=True)
        prep = {"removed_entities":[],"removed_constraints":[]}
        if shared_source:
            condition = read_json(shared_source/"candidates"/candidate/"condition.json")
            assert condition["domain"] == slot["domain"] and condition["subtype"] == slot["subtype"]
            condition["run_id"] = runners["whole"].cfg["run_id"]
            inputs = {"config_hash":runners["whole"].cfg["config_hash"],
                      "slot":{k:slot[k] for k in ("slot_id","domain","subtype")},"ordinal":1}
            runners["whole"].stage(candidate,1,inputs,lambda c=condition:c)
            try:
                plan, prep = shared_plan(shared_source,candidate,condition)
            except StageFailure as exc:
                stores["whole"].finish_candidate(candidate,"rejected",2,[i.json() for i in exc.issues])
            else:
                stores["whole"].save_artifact(candidate,"plan.json",plan)
                stores["whole"].save_artifact(candidate,"experiment/shared_preparation.json",prep)
                runners["whole"].stage(candidate,2,{"shared_plan_hash":digest(plan)},lambda p=plan:p)
                runners["whole"].run_candidate(slot,candidate,1,stop_after=3)
        else:
            runners["whole"].run_candidate(slot,candidate,1,stop_after=3)
        base_status = stores["whole"].rows("SELECT status,final_stage FROM candidates WHERE candidate_id=?",(candidate,))[0]
        if base_status != {"status":"paused","final_stage":3}:
            report["shared_plan_failures"].append(summarize(stores["whole"],candidate))
            atomic_json(report_path,report)
            continue
        condition = read_json(stores["whole"].run_dir/"candidates"/candidate/"condition.json")
        plan = read_json(stores["whole"].run_dir/"candidates"/candidate/"plan.json")
        check_plan({key:plan[key] for key in PLAN["properties"]},condition)
        split_slot = stores["split"].rows("SELECT * FROM slots WHERE domain=?",(domain,))[0]
        assert split_slot["subtype"] == slot["subtype"]
        assert register(stores["split"],split_slot) == candidate
        split_condition = {**condition,"run_id":runners["split"].cfg["run_id"]}
        inputs = {"config_hash":runners["split"].cfg["config_hash"],
                  "slot":{k:split_slot[k] for k in ("slot_id","domain","subtype")},"ordinal":1}
        runners["split"].stage(candidate,1,inputs,lambda c=split_condition:c)
        stores["split"].save_artifact(candidate,"plan.json",plan)
        runners["split"].stage(candidate,2,{"shared_plan_hash":digest(plan)},lambda p=plan:p)
        runners["split"].run_candidate(split_slot,candidate,1,stop_after=3)
        split_values = read_json(stores["split"].run_dir/"candidates"/candidate/"value_map.json")
        values = read_json(stores["whole"].run_dir/"candidates"/candidate/"value_map.json")
        assert split_values == values
        assert condition_input(condition) == condition_input(split_condition)
        cases.append((candidate,slot,split_slot,condition,plan,values,prep))
        atomic_json(report_path,report)
    for index,(candidate,slot,split_slot,condition,plan,values,prep) in enumerate(cases):
        pair = {"candidate_id":candidate,"domain":condition["domain"],"subtype":condition["subtype"],
                "layout_variant":condition["layout_variant"],"length_target":condition["length_target"],
                "min_chars":condition["min_chars"],"relation_count":len(plan["relations"]),
                "privacy_counts":dict(Counter(r["target_privacy"] for r in plan["relations"])),
                "plan_hash":digest(plan),"value_map_hash":digest(values),"shared_preparation":prep,"arms":{}}
        for arm in (("whole","split") if index%2 == 0 else ("split","whole")):
            print(f"DRAFT {candidate} {arm}",flush=True)
            store = stores[arm]
            store.execute("UPDATE candidates SET status='running',finished_at=NULL WHERE candidate_id=?",(candidate,))
            runners[arm].run_candidate(slot if arm == "whole" else split_slot,candidate,1)
            outcome = summarize(store,candidate)
            outcome["generation_review_cost_usd"] = sum(c["estimated_cost_usd"] for c in outcome["calls"] if c["task"] != "plan")
            pair["arms"][arm] = outcome
            print(f"RESULT {candidate} {arm} {outcome['status']} stage={outcome['final_stage']} reasons={[i['code'] for i in outcome['reasons']]}",flush=True)
            store.manifest()
            export(store,runners[arm].cfg)
            atomic_json(report_path,{**report,"in_progress_pair":pair})
        report["pairs"].append(pair)
        atomic_json(report_path,report)
    report["finished_at"] = now()
    report["totals"] = {}
    for arm in stores:
        outcomes = [p["arms"][arm] for p in report["pairs"]]
        calls = [c for o in outcomes for c in o["calls"] if c["task"] != "plan"]
        report["totals"][arm] = {"evaluated":len(outcomes),"accepted":sum(o["status"] == "accepted" for o in outcomes),
            "calls_by_task":dict(Counter(c["task"] for c in calls)),"generation_review_cost_usd":sum(c["estimated_cost_usd"] for c in calls),
            "reached_review":sum(bool(o["grades"]) for o in outcomes),
            "initial_issues":dict(Counter(code for o in outcomes for code,n in (o["diagnoses"][0]["issue_counts"].items() if o["diagnoses"] else []) for _ in range(n))),
            "final_reject_codes":dict(Counter(i["code"] for o in outcomes for i in o["reasons"]))}
    atomic_json(report_path,report)
    print(f"REPORT {report_path}",flush=True)
    print(report["totals"],flush=True)
    for store in stores.values():
        store.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix",required=True)
    parser.add_argument("--shared-plans-from",type=Path)
    args = parser.parse_args()
    run(args.prefix,args.shared_plans_from)
