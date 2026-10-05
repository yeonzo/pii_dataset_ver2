"""Input: slot/quota/catalog. Output: document conditions and privacy targets."""
from __future__ import annotations

import math
import random

from ..common import digest, fail
from ..formats import CATALOG, VARIANTS, format_for, sections_for
from ..persons import select_people
from ..coverage import select_required
from ..privacy import POLICY_HASH
from ..semantic_profiles import profile_for
from ..document_purpose import apply_purpose
from ..document_specs import apply_spec
from ..reference_people import random_reference, select_reference
from ..planning_seed import plan_organization_bridges
import json


def select_condition(cfg: dict, store, slot: dict, candidate: str, ordinal: int) -> dict:
    domain, subtype = slot["domain"], slot["subtype"]
    subtype_info = CATALOG["domains"][domain][subtype]
    rng = random.Random(int(digest([cfg["seed"], slot["slot_id"], ordinal])[:16], 16))
    fmt, fixed, variants = format_for(domain, subtype)
    counts = {row["layout_variant"]: row["n"] for row in store.rows("SELECT layout_variant,COUNT(*) n FROM candidates WHERE status='accepted' AND document_format=? GROUP BY layout_variant", (fmt,))}
    override = cfg["selection"].get("variant")
    if cfg.get('spec_policy')=='type_specs_v1':
        if override not in (None,'type_spec'):
            fail('VARIANT_SELECTION','type_specs_v1 uses subtype-specific type_spec layouts','STOP_RUN',True)
        override=None  # Transitional generic sections are replaced by apply_spec below.
    if override and override not in variants:
        fail("VARIANT_SELECTION", f"{override} incompatible with {fmt}", "STOP_RUN", True)
    least = min(counts.get(v, 0) for v in variants)
    variant = override or rng.choice([v for v in variants if counts.get(v, 0) == least])
    topics = CATALOG["topics"][domain]
    if isinstance(topics, dict):
        # These dictionaries map subtype to its purpose, not independent topics.
        topics = [topics[subtype]] if subtype in topics else list(topics.values())
    topic_index = rng.randrange(len(topics))
    topic = cfg["selection"].get("topic") or topics[topic_index]
    target = rng.randint(*subtype_info["length_range"])
    n = rng.randint(*cfg["relation_count_range"])
    nnon = min(n-1, max(2, round(n * rng.uniform(*cfg["non_pii_relation_fraction_range"]))))
    viewpoint = cfg["selection"].get("viewpoint") or ("official_record" if fixed else rng.choice(["staff_record", "party_statement_summary"]))
    supplemental = store.rows("SELECT required_types FROM coverage_slots WHERE slot_id=?",(slot["slot_id"],))
    forced = json.loads(supplemental[0]["required_types"]) if supplemental else []
    people = select_people(domain,subtype,rng,minimum=2 if "PERSONAL_RELATIONSHIP" in forced else 1)
    condition = {
        "run_id": cfg["run_id"], "slot_id": slot["slot_id"], "candidate_id": candidate, "condition_version": ordinal,
        "domain": domain, "subtype": subtype, "subtype_label": subtype_info["label"], "contract_category": subtype_info["category"],
        "document_format": fmt, "layout_variant": variant, "layout_variant_label": VARIANTS[variant][0], "fixed_format": fixed,
        "narrative_viewpoint": viewpoint, "topic_id": f"{domain}_topic_{topic_index:03d}" if not cfg["selection"].get("topic") else "custom_" + digest(topic)[:10], "topic": topic,
        "section_plan": sections_for(variant, target), "length_target": target,
        "min_chars": max(int(cfg.get("min_chars_floor", 1500)), int(target * .75)),
        "relation_count": n, "pii_relation_target": n-nnon, "non_pii_relation_target": nnon, "non_pii_only_min": cfg["non_pii_only_min"],
        "mention_policy": cfg["mention_policy"],
        "expression_policy": cfg["expression_policy"],
        "graph_policy": cfg.get("graph_policy", "legacy"),
        "allowed_personal_types": subtype_info["personal_types"], "allowed_public_types": ["WORKPLACE", "DEPARTMENT", "POSITION", "SCHOOL", "MAJOR", "ADDRESS", "TELEPHONE", "MOBILE_PHONE", "EMAIL", "BANK_ACCOUNT_NUMBER"],
        "name_context_policy": "Actual applicant/patient/party remains PII. Example NAME may be NON_PII only in a supported example scene; do not extend fictional NAME to demographic/identifier attributes. No unverified public figures.",
        **people,"privacy_policy_version":cfg["privacy_policy_version"],"privacy_policy_hash":POLICY_HASH,
    }
    condition=apply_spec(apply_purpose(condition,cfg),cfg,rng)
    condition["coverage_requirements"] = select_required(store,cfg,condition,forced)
    condition['generation_flow'] = cfg.get('generation_flow','legacy')
    condition["required_relation_types"] = [r["relation"] for r in condition["coverage_requirements"]]
    condition["graph_profile_applied"] = profile_for(condition) is not None
    condition["purpose_review"] = cfg.get("purpose_review",False)
    condition['review_evidence_policy']=cfg.get('review_evidence_policy','quoted')
    condition['relation_review_policy']=cfg.get('relation_review_policy','full_evidence_v1')
    if set(forced)-set(condition["required_relation_types"]):
        fail("COVERAGE_CONDITION_CAPACITY","Required relation cannot fit this subtype/person/privacy allocation","STOP_CANDIDATE")
    return plan_organization_bridges(random_reference(select_reference(condition,cfg),cfg),cfg)
