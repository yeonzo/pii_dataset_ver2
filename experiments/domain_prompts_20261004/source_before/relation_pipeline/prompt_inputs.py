"""Project task inputs; keep audit identifiers and diagnostic statistics local."""
from __future__ import annotations

import copy


DOCUMENT_FIELDS = ("domain", "subtype", "subtype_label", "contract_category","n_parties","person_count_scope","person_slots","max_example_persons","required_relation_types",
                   "document_format", "layout_variant", "layout_variant_label",
                   "fixed_format", "narrative_viewpoint", "topic", "length_target", "min_chars", "document_brief", "reference_context", "document_spec")
SECTION_FIELDS = ("section_id", "title", "allowed_kinds", "target_chars", "required", "mode", "structure", "fact_fields")
PLAN_FIELDS = ("entities", "relations", "scenes", "slot_constraints","persons","person_entity_links")
LENGTH_FIELDS = ("rendered_chars", "min_chars", "shortage_chars", "section_chars", "section_shortages")


def condition_input(condition: dict, planning=False) -> dict:
    from .content_depth import content_depth
    fields = DOCUMENT_FIELDS + (("allowed_personal_types", "allowed_public_types") if planning else ())
    result = {key:copy.deepcopy(condition[key]) for key in fields if key in condition}
    result['content_depth'] = content_depth(condition)
    result["section_plan"] = [{key:copy.deepcopy(section[key]) for key in SECTION_FIELDS if key in section}
                              for section in condition["section_plan"]]
    return result


def plan_input(plan: dict) -> dict:
    result={key:copy.deepcopy(plan.get(key, [])) for key in PLAN_FIELDS}
    if 'document_story' in plan:
        result['document_story']=copy.deepcopy(plan['document_story'])
    if 'document_case' in plan:
        result['document_case']=copy.deepcopy(plan['document_case'])
    return result


def diagnosis_input(diagnosis: dict) -> dict:
    metrics = diagnosis.get("metrics", {})
    # Mention distributions are observations, never instructions to balance/repeat.
    return {"issues":compact_issues(diagnosis.get("issues", [])),
            "metrics":{key:copy.deepcopy(metrics[key]) for key in LENGTH_FIELDS if key in metrics}}


def compact_issues(issues):
    groups = {}
    for issue in issues:
        key = tuple(issue.get(k,"") for k in ("code","message","action"))
        groups.setdefault(key,[]).append(issue)
    result = []
    for (code,message,action),items in groups.items():
        if len(items) == 1:
            result.append(copy.deepcopy(items[0]))
            continue
        targets = []
        for item in items:
            target = {k:item[k] for k in ("entity_id","relation_id","sentence_id","section_id") if item.get(k)}
            if target not in targets:
                targets.append(target)
        result.append({"code":code,"message":message,"action":action,"targets":targets})
    return result
