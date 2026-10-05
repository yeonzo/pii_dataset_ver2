"""Audit-derived reporting. Estimates use observed terminal candidates only."""
from __future__ import annotations

import collections
import csv
import json
import math
from pathlib import Path

from .common import STAGES, atomic_json, now, read_json
from .coverage import coverage_state,completion_state,final_relation_rows


def person_rows(store,candidates):
    rows = []
    for c in candidates:
        folder = store.run_dir/"candidates"/c["candidate_id"]
        plan_path,review_path = folder/"plan.json",folder/"review.json"
        if not plan_path.exists():
            continue
        plan = read_json(plan_path)
        observed = read_json(review_path).get("review",{}).get("person_checks",{}) if review_path.exists() else {}
        by_name = {p["name_entity_id"]:p for p in observed.get("observed_persons",[])}
        condition = json.loads(c.get("condition_json") or "{}")
        for person in plan.get("persons",[]):
            rows.append({"candidate_id":c["candidate_id"],"candidate_status":c["status"],"domain":c["domain"],"subtype":c["subtype"],
                "n_parties_target":condition.get("n_parties"),**person,"observed_role":by_name.get(person["name_entity_id"],{}).get("role"),
                "observed_context_kind":by_name.get(person["name_entity_id"],{}).get("context_kind"),
                "observed_actual_count":observed.get("actual_person_count"),
                "entity_links":[l for l in plan.get("person_entity_links",[]) if l["person_id"] == person["person_id"]]})
    return rows


def review_relation_rows(store, candidates, reviews):
    """Read stored judgments without extra model calls or counting retries as cases."""
    candidate_map = {c["candidate_id"]: c for c in candidates}
    plans = {}
    rows, unavailable = [], []
    for record in reviews:
        cid, version = record["candidate_id"], record["version"]
        if cid not in candidate_map:
            continue
        folder = store.run_dir / "candidates" / cid
        path = folder / "review_versions" / f"review_v{version}.json"
        if not path.is_file():
            # Invalid-schema responses preserve grades, but are not semantic observations.
            if record["response_valid"]:
                unavailable.append({"candidate_id": cid, "review_version": version})
            continue
        artifact = read_json(path)
        observed = artifact.get("review", {})
        checks = artifact.get("checks", {})
        if cid not in plans:
            plan_path = folder / "plan.json"
            plans[cid] = {r["relation_id"]: r for r in read_json(plan_path).get("relations", [])} if plan_path.is_file() else {}
        expressions = {c["relation_id"]: c for c in checks.get("expression_checks", [])}
        for relation in observed.get("relation_checks", []):
            rid = relation["relation_id"]
            planned = plans[cid].get(rid, {})
            groups = relation.get("evidence_groups", [])
            sizes = [len(group) for group in groups if group]
            expression = expressions.get(rid, {})
            mode = expression.get("observed_mode")
            valid = expression.get("evidence_valid")
            source = "independent_review_final_order" if mode is not None else "unavailable"
            # Historical artifacts verified equality to a planned mode. Keep that
            # provenance explicit; a failed/missing comparison is never an observation.
            if mode is None and expression.get("passed") and planned.get("expression_mode"):
                mode, valid, source = planned["expression_mode"], True, "legacy_verified_plan_match"
            rows.append({
                "candidate_id": cid, "candidate_status": candidate_map[cid]["status"],
                "domain": candidate_map[cid]["domain"], "subtype": candidate_map[cid]["subtype"],
                "review_version": version, "draft_revision": artifact.get("draft_revision"),
                "reviewed_body_hash": artifact.get("reviewed_body_hash"),
                "response_valid": bool(record["response_valid"]), "relation_id": rid,
                "planned_privacy": planned.get("target_privacy"),
                "observed_privacy": relation.get("observed_privacy"),
                "planned_expression_mode": planned.get("expression_mode"),
                "observed_expression_mode": mode,
                "expression_classification_source": source,
                "expression_passed": valid,
                "reviewer_single_sentence_claim": expression.get("reviewer_single_sentence_claim"),
                "single_sentence_claim_consistent": expression.get("single_sentence_claim_consistent"),
                "extractable": relation.get("extractable"),
                "direction_supported": relation.get("direction_supported"),
                "coreference_unambiguous": relation.get("coreference_unambiguous"),
                "single_sentence_sufficient": relation.get("single_sentence_sufficient"),
                "minimum_evidence_sentence_count": min(sizes) if sizes else None,
                "evidence_groups": groups, "reason": relation.get("reason", ""),
            })
    return rows, unavailable


def selection_audit(candidates, reviews, relation_rows, unavailable):
    latest = {r["candidate_id"]: r for r in reviews}
    valid_latest = {cid: r for cid, r in latest.items() if r["response_valid"]}
    latest_relations = [r for r in relation_rows if r["candidate_id"] in valid_latest
                        and r["review_version"] == valid_latest[r["candidate_id"]]["version"]]
    observed_candidates = {r["candidate_id"] for r in latest_relations}
    ambiguous_latest = {r["candidate_id"] for r in latest_relations if r["observed_privacy"] == "AMBIGUOUS"}
    ambiguous_ever = {r["candidate_id"] for r in relation_rows if r["response_valid"] and r["observed_privacy"] == "AMBIGUOUS"}
    status = {c["candidate_id"]: c["status"] for c in candidates}
    confirmed = [r for r in latest_relations if r["candidate_status"] == "accepted"
                 and r["expression_passed"] and r["extractable"] and r["direction_supported"]
                 and r["coreference_unambiguous"] and r["observed_privacy"] == r["planned_privacy"]]
    expression_counts = collections.Counter(r["observed_expression_mode"] for r in confirmed)
    context = [r for r in confirmed if r["observed_expression_mode"] in ("adjacent", "nonadjacent")
               and not r["single_sentence_sufficient"] and (r["minimum_evidence_sentence_count"] or 0) >= 2]
    outcomes = lambda ids: dict(collections.Counter(status[cid] for cid in ids))
    label_mode = collections.Counter((r["candidate_status"], r["observed_expression_mode"], r["observed_privacy"]) for r in latest_relations)
    return {
        "reviewed_candidates": len(latest),
        "valid_latest_review_candidates": len(valid_latest),
        "invalid_latest_review_candidates": len(latest)-len(valid_latest),
        "candidates_with_available_latest_relation_observations": len(observed_candidates),
        "latest_observed_privacy_counts": dict(collections.Counter(r["observed_privacy"] for r in latest_relations)),
        "latest_ambiguous_candidates": len(ambiguous_latest),
        "latest_ambiguous_candidate_outcomes": outcomes(ambiguous_latest),
        "ever_ambiguous_candidates": len(ambiguous_ever),
        "ever_ambiguous_candidate_outcomes": outcomes(ambiguous_ever),
        "latest_ambiguity_candidate_rate": len(ambiguous_latest)/len(observed_candidates) if observed_candidates else None,
        "accepted_confirmed_expression_counts": dict(expression_counts),
        "accepted_observed_expression_counts": dict(expression_counts),
        "accepted_confirmed_multisentence_relations": len(context),
        "accepted_candidates_with_confirmed_multisentence_relations": len({r["candidate_id"] for r in context}),
        "latest_relation_counts_by_outcome_mode_privacy": [
            {"candidate_status": k[0], "observed_expression_mode": k[1], "observed_privacy": k[2], "count": n}
            for k, n in sorted(label_mode.items(), key=lambda item: tuple(str(x) for x in item[0]))],
        "missing_valid_review_artifacts": unavailable,
        "basis": "Latest response-valid judgment per candidate; all valid versions are used only for ever_ambiguous counts. Language quality and privacy certainty are separate. Evidence counts describe context requirements, not calibrated task difficulty; reviewer selection bias remains.",
    }


def repair_audit(store, candidate_ids):
    rows = []
    for event in store.rows("SELECT candidate_id,payload FROM events WHERE kind='repair_evaluated' ORDER BY id"):
        if event["candidate_id"] in candidate_ids:
            rows.append({"candidate_id":event["candidate_id"],**json.loads(event["payload"])})
    return {"evaluated_attempts":len(rows),"structural_targets_satisfied":sum(r["structural_targets_satisfied"] for r in rows),
            "all_code_checks_passed":sum(r["all_code_checks_passed"] for r in rows),
            "no_effective_progress":sum(r["no_effective_progress"] for r in rows),
            "length_only_progress":sum(r["length_only_progress"] for r in rows),
            "remaining_missing_entity_count":sum(len(r["remaining_missing_entities"]) for r in rows),
            "remaining_invalid_relation_count":sum(len(r["remaining_invalid_relation_ids"]) for r in rows),
            "semantic_verification":"These are code checks; final semantic correctness requires independent review.","attempts":rows}


def dataset_design(cfg, candidates):
    from .semantic_profiles import profile_for
    selected = [json.loads(c["condition_json"]) for c in candidates if c.get("condition_json")]
    expressions = collections.Counter()
    for condition in selected:
        expressions.update(condition.get("expression_targets", {}))
    controls = ("graph_policy", "relation_count_range", "non_pii_relation_fraction_range", "non_pii_only_min", "relation_coverage")
    legacy = ("repeat_entities_per_group", "repeat_mentions_range", "pii_mention_share_bounds",
                "min_scenes_per_privacy_group", "min_document_thirds_per_privacy_group")
    return {"classification": "controlled_synthetic_documents", "frequency_representative": False,
            "configured_controls": {k: cfg[k] for k in controls if k in cfg},
            "legacy_configured_controls": {k: cfg[k] for k in legacy if k in cfg},
            "mention_policy": cfg.get("mention_policy", "legacy_controlled"),
            "expression_policy": cfg.get("expression_policy", "legacy_allocated"),
            "selected_relation_count_counts": dict(collections.Counter(c.get("relation_count") for c in selected)),
            "selected_graph_profile_counts": dict(collections.Counter(
                "scenario_profile" if c.get("graph_profile_applied",profile_for(c) is not None) else "domain_ontology_fallback"
                for c in selected)),
            "selected_person_count_counts": dict(collections.Counter(c.get("n_parties") for c in selected)),
            "person_count_scope":"Registered named main participants; not a repetition or position quota.",
            "selected_expression_target_totals": dict(expressions),
            "basis": "Selected targets include rejected and unfinished candidates; they are design allocations, not observed final-body distributions. Accepted actual mentions and independently confirmed relation evidence are reported separately."}


def wilson(successes: int, trials: int):
    if trials == 0:
        return None
    z = 1.96
    p = successes/trials
    center = (p+z*z/(2*trials))/(1+z*z/trials)
    half = z*math.sqrt(p*(1-p)/trials+z*z/(4*trials*trials))/(1+z*z/trials)
    return [max(0,center-half),min(1,center+half)]


def snapshot(store, cfg: dict, domain=None) -> dict:
    candidates = store.rows("SELECT * FROM candidates" + (" WHERE domain=?" if domain else ""), (domain,) if domain else ())
    ids = {c["candidate_id"] for c in candidates}
    attempts = [a for a in store.rows("SELECT * FROM stage_attempts ORDER BY id") if a["candidate_id"] in ids]
    reviews = [r for r in store.rows("SELECT * FROM reviews ORDER BY id") if r["candidate_id"] in ids]
    calls = [c for c in store.rows("SELECT * FROM api_calls ORDER BY id") if c["candidate_id"] in ids]
    stages = []
    for number,name in STAGES.items():
        if number == 0:
            continue
        rows = [a for a in attempts if a["stage"] == number]
        latest = {a["candidate_id"]:a for a in rows}
        counts = collections.Counter(a["status"] for a in rows)
        latest_counts = collections.Counter(a["status"] for a in latest.values())
        passes = sum(a["status"] in ("passed","cached") for a in latest.values())
        # Running/interrupted checks are excluded from the completed denominator.
        completed = sum(a["status"] not in ("running","interrupted") for a in latest.values())
        reasons = collections.Counter(i["code"] for a in rows for i in json.loads(a["reasons"]))
        reason_candidates = collections.defaultdict(set)
        for attempt in rows:
            for reason in json.loads(attempt["reasons"]):
                reason_candidates[reason["code"]].add(attempt["candidate_id"])
        final_rejections = sum(c["status"] == "rejected" and c["final_stage"] == number for c in candidates)
        final_errors = sum(c["status"] == "error" and c["final_stage"] == number for c in candidates)
        stages.append({"stage":number,"name":name,"attempts":len(rows),"attempt_status_counts":dict(counts),"unique_candidates":len(latest),"latest_candidate_status_counts":dict(latest_counts),"final_rejections_count":final_rejections,"final_errors_count":final_errors,"latest_candidate_pass_rate":passes/completed if completed else None,"pass_rate_wilson_95":wilson(passes,completed),"reason_counts":dict(reasons),"reason_candidate_counts":{k:len(v) for k,v in reason_candidates.items()}})
    grades_latest = {r["candidate_id"]:r for r in reviews}
    grade_counts = {dimension:dict(collections.Counter(grades_latest.get(c["candidate_id"], {}).get(dimension) or "미판정" for c in candidates)) for dimension in ("overall","consistency","fluency","suitability")}
    grouped = collections.defaultdict(collections.Counter)
    for c in candidates:
        key = (c["domain"],c["subtype"],c["document_format"] or "",c["layout_variant"] or "")
        grouped[key][c["status"]] += 1
    selections = [{"domain":k[0],"subtype":k[1],"document_format":k[2],"layout_variant":k[3],"counts":dict(v)} for k,v in sorted(grouped.items())]
    slots = [s for s in store.rows("SELECT * FROM slots") if domain is None or s["domain"] == domain]
    remaining = sum(s["status"] != "accepted" for s in slots)
    success = sum(c["status"] == "accepted" for c in candidates)
    rejected = sum(c["status"] == "rejected" for c in candidates)
    terminals = success+rejected
    p = success/terminals if terminals else None
    interval = wilson(success,terminals)
    estimates = {"accepted":success,"rejected":rejected,"remaining_slots":remaining,"observed_acceptance_rate":p,"wilson_95":interval,"expected_additional_candidates":math.ceil(remaining/p) if p else None,"candidate_estimate_range":([math.ceil(remaining/interval[1]),math.ceil(remaining/interval[0])] if interval and interval[0]>0 else None),"basis":"Observed accepted/rejected candidates; errors and interruptions excluded. Not a completion guarantee; slot difficulty/quota may differ.","offline_fixture_only":cfg["mode"] == "offline"}
    terminal_ids = {c["candidate_id"] for c in candidates if c["status"] in ("accepted", "rejected")}
    expected = estimates["expected_additional_candidates"]
    for stage in stages:
        latest = {a["candidate_id"]: a for a in attempts if a["stage"] == stage["stage"] and a["candidate_id"] in terminal_ids}
        passed = sum(a["status"] in ("passed", "cached") for a in latest.values())
        stage["forecast"] = {
            "estimated_additional_entries": round(expected*len(latest)/terminals, 2) if expected is not None and terminals else None,
            "estimated_additional_passes": round(expected*passed/terminals, 2) if expected is not None and terminals else None,
            "estimated_additional_nonpasses": round(expected*(len(latest)-passed)/terminals, 2) if expected is not None and terminals else None,
            "basis": "Latest stage result of terminal candidates; extrapolated using observed overall acceptance. Retry calls are not extra candidates.",
        }
    by_domain = []
    coverage_slots = {s["slot_id"] for s in store.rows("SELECT slot_id FROM coverage_slots")}
    for selected_domain in sorted({s["domain"] for s in slots}):
        local = [c for c in candidates if c["domain"] == selected_domain]
        accepted_count = sum(c["status"] == "accepted" for c in local)
        rejected_count = sum(c["status"] == "rejected" for c in local)
        denominator = accepted_count+rejected_count
        by_domain.append({"domain": selected_domain, "slots": sum(s["domain"] == selected_domain for s in slots),
                          "base_quota_slots":sum(s["domain"] == selected_domain and s["slot_id"] not in coverage_slots for s in slots),
                          "coverage_supplemental_slots":sum(s["domain"] == selected_domain and s["slot_id"] in coverage_slots for s in slots),
                          "accepted": accepted_count, "rejected": rejected_count,
                          "remaining_slots": sum(s["domain"] == selected_domain and s["status"] != "accepted" for s in slots),
                          "observed_acceptance_rate": accepted_count/denominator if denominator else None})
    usage = collections.defaultdict(lambda: {"requests":0,"input_tokens":0,"cached_input_tokens":0,"output_tokens":0,"estimated_cost_usd":0.0})
    for c in calls:
        row = usage[(c["model"],c["key_slot"])]
        row["requests"] += 1
        for k in ("input_tokens","cached_input_tokens","output_tokens","estimated_cost_usd"):
            row[k] += c[k]
    accepted_rows = [a for a in store.rows("SELECT * FROM accepted") if a["candidate_id"] in ids]
    appearance = collections.Counter()
    type_mentions = collections.Counter()
    repeated_entities = collections.Counter()
    repetition_histogram = collections.Counter()
    for a in accepted_rows:
        metrics = json.loads(a["metrics"])
        appearance.update(metrics.get("mention_counts",{}))
        repeated_entities.update(metrics.get("repeated_entities_by_group", {}))
        for entity in metrics.get("entities",{}).values():
            type_mentions[entity["entity_type"]] += entity["mentions"]
            repetition_histogram[entity["mentions"]] += 1
    final_reasons = collections.Counter(i["code"] for c in candidates if c["status"] == "rejected" for i in json.loads(c["reasons"]))
    final_reason_candidates = collections.Counter(code for c in candidates if c["status"] == "rejected" for code in {i["code"] for i in json.loads(c["reasons"])})
    relation_rows, unavailable = review_relation_rows(store, candidates, reviews)
    return {"run_id":cfg["run_id"],"mode":cfg["mode"],"generated_at":now(),"relation_coverage":coverage_state(store,cfg,domain),"completion":completion_state(store,cfg),"person_audit":person_rows(store,candidates),"dataset_design":dataset_design(cfg,candidates),"selection_audit":selection_audit(candidates,reviews,relation_rows,unavailable),"repair_audit":repair_audit(store,ids),"candidate_status_counts":dict(collections.Counter(c["status"] for c in candidates)),"stages":stages,"by_domain":by_domain,"selections":selections,"quality_latest_per_candidate":grade_counts,"quality_review_attempts":len(reviews),"final_rejection_reasons":dict(final_reasons),"final_rejection_reason_candidate_counts":dict(final_reason_candidates),"forecast":estimates,"usage":[{"model":k[0],"key_slot":k[1],**v} for k,v in usage.items()],"accepted_mention_counts":dict(appearance),"accepted_mentions_by_type":dict(type_mentions),"accepted_repeated_entities_by_group":dict(repeated_entities),"accepted_entity_mention_count_histogram":dict(repetition_histogram)}


def export_csv(path: Path, rows: list[dict], fields=None):
    path.parent.mkdir(parents=True,exist_ok=True)
    if fields is None:
        fields = list(rows[0]) if rows else []
    with path.open("w",encoding="utf-8-sig",newline="") as stream:
        writer = csv.DictWriter(stream,fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k:json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v for k,v in row.items()})


def export(store, cfg: dict):
    result = snapshot(store,cfg)
    folder = store.run_dir/"statistics"
    atomic_json(folder/"summary.json",result)
    export_csv(folder/"stages.csv",result["stages"])
    export_csv(folder/"selections.csv",result["selections"])
    export_csv(folder/"domains.csv",result["by_domain"])
    for table in ("candidates","stage_attempts","reviews","api_calls","slots","events"):
        export_csv(folder/(table+".csv"),store.rows("SELECT * FROM "+table+" ORDER BY rowid"))
    export_csv(folder/"accepted_distribution.csv",[{"candidate_id":a["candidate_id"],"document_id":a["document_id"],**json.loads(a["metrics"])} for a in store.rows("SELECT * FROM accepted")])
    relations, _ = review_relation_rows(store, store.rows("SELECT * FROM candidates"), store.rows("SELECT * FROM reviews ORDER BY id"))
    export_csv(folder/"review_relations.csv", relations)
    export_csv(folder/"repair_progress.csv",result["repair_audit"]["attempts"])
    export_csv(folder/"accepted_relations.csv",final_relation_rows(store))
    export_csv(folder/"relation_coverage.csv",result["relation_coverage"]["counts"])
    export_csv(folder/"persons.csv",result["person_audit"])
    return result


def display(result: dict) -> str:
    lines = [f"run={result['run_id']} mode={result['mode']}","후보 상태: "+json.dumps(result["candidate_status_counts"],ensure_ascii=False),"stage                candidates passed rejected repair errors attempts"]
    for stage in result["stages"]:
        counts = stage["latest_candidate_status_counts"]
        # Repair describes the last diagnostic; rejected is the candidate's final exit.
        lines.append(f"{stage['stage']:02d} {stage['name']:<18} {stage['unique_candidates']:>5} {counts.get('passed',0)+counts.get('cached',0):>6} {stage['final_rejections_count']:>8} {counts.get('repair_needed',0):>6} {stage['final_errors_count']:>6} {stage['attempts']:>8}")
    lines.append("품질 등급(후보별 최신): "+json.dumps(result["quality_latest_per_candidate"],ensure_ascii=False))
    lines.append("도메인별 수량: "+json.dumps(result["by_domain"],ensure_ascii=False))
    coverage = result["relation_coverage"]
    lines.append(f"관계 커버리지: {coverage['covered_type_count']}/{coverage['required_type_count']}종, 전체 완료={result['completion']['complete']}, 미달={','.join(coverage['missing_types'])}")
    lines.append("탈락 사유별 후보 수: "+json.dumps(result["final_rejection_reason_candidate_counts"],ensure_ascii=False))
    audit = result["selection_audit"]
    lines.append("모호성·문장 간 근거: "+json.dumps({"valid_review_candidates":audit["valid_latest_review_candidates"],"latest_ambiguous_candidates":audit["latest_ambiguous_candidates"],"ever_ambiguous_candidate_outcomes":audit["ever_ambiguous_candidate_outcomes"],"accepted_observed_expression_counts":audit["accepted_observed_expression_counts"]},ensure_ascii=False))
    lines.append("추정: "+json.dumps(result["forecast"],ensure_ascii=False))
    lines.append("사용량: "+json.dumps(result["usage"],ensure_ascii=False))
    return "\n".join(lines)
