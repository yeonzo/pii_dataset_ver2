"""Input: resources/config. Output: frozen run configuration, slots and ledger."""
from __future__ import annotations

import random
import re
from pathlib import Path

from ..common import DOMAINS, ROOT, TYPES, atomic_json, digest, fail, file_hash, now, read_json
from ..formats import CATALOG, ONTOLOGY, allowed_triples, format_catalog, format_for
from ..store import Store
from ..coverage import RELATION_TYPES,eligible_targets
from ..privacy import POLICY,POLICY_HASH
from ..persons import party_range,role_ids


def resource_hashes(cfg: dict) -> dict:
    pool = Path(cfg["pool_path"])
    if not pool.is_file():
        fail("POOL_MISSING", str(pool), fatal=True)
    paths = [ROOT / "assets/catalog.json", ROOT / "assets/ontology.json", ROOT / "assets/reference_people.json", pool]
    paths += sorted((ROOT / "relation_pipeline").rglob("*.py"))
    hashes = {str(p): file_hash(p) for p in paths}
    reference = cfg.get("reference_dataset")
    if reference and not Path(reference).is_file():
        fail("REFERENCE_MISSING", reference, fatal=True)
    if reference:
        hashes[reference] = file_hash(Path(reference))
    hashes["allowed_triples_policy"] = digest({d: allowed_triples(d) for d in DOMAINS})
    return hashes


def prepare(config: dict, run_id: str, domains=None, target=None, selection=None, mode="live") -> Store:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        fail("RUN_ID", "Use only letters, digits, underscore and hyphen", fatal=True)
    cfg = dict(config)
    if cfg.get('spec_policy','legacy') not in {'legacy','type_specs_v1'}:
        fail('SPEC_POLICY','Unknown document spec policy','STOP_RUN',True)
    if cfg.get('generation_flow','legacy') not in {'legacy','separated_v1'}:
        fail('GENERATION_FLOW','Unknown generation flow','STOP_RUN',True)
    if cfg.get('generation_flow')=='separated_v1' and (cfg['max_provider_requests_per_candidate']>7 or 'expand' not in cfg['max_output_tokens']):
        fail('CALL_POLICY','Separated flow requires at most 7 calls and an expand output budget','STOP_RUN',True)
    cfg.update(run_id=run_id, domains=list(domains or DOMAINS), target_per_domain=target if target is not None else cfg["target_per_domain"], selection=selection or {}, mode=mode)
    if not cfg["domains"] or len(set(cfg["domains"])) != len(cfg["domains"]) or any(d not in DOMAINS for d in cfg["domains"]):
        fail("DOMAIN_CONFIG", "Invalid domain selection", fatal=True)
    if cfg["target_per_domain"] < 1:
        fail("TARGET_CONFIG", "target_per_domain must be positive", fatal=True)
    if cfg["generation_model"] != "gpt-4o-mini" or cfg["review_model"] != "gpt-5-mini":
        fail("MODEL_CONFIG", "Requested routing is gpt-4o-mini / gpt-5-mini", fatal=True)
    if cfg["max_document_actions"] < 1 or cfg["run_request_budget"] < 1 or cfg["run_cost_budget_usd"] <= 0:
        fail("BUDGET_CONFIG", "Invalid action/request/cost limits", fatal=True)
    for field in ("max_plan_attempts", "max_review_response_attempts", "max_provider_requests_per_candidate", "max_candidates_per_slot", "max_candidates_per_domain", "request_timeout_seconds"):
        if not isinstance(cfg[field], (int, float)) or cfg[field] <= 0:
            fail("BUDGET_CONFIG", field + " must be positive", fatal=True)
    for field, lower, upper in (("relation_count_range", 3, None), ("non_pii_relation_fraction_range", 0, 1)):
        bounds = cfg[field]
        if not isinstance(bounds, list) or len(bounds) != 2 or not lower <= bounds[0] <= bounds[1] or (upper is not None and bounds[1] > upper):
            fail("RANGE_CONFIG", field, fatal=True)
    if cfg.get("mention_policy") != "natural" or cfg.get("expression_policy") != "observe_only":
        fail("POLICY_CONFIG", "Use natural mentions and observe_only expression classification", fatal=True)
    if cfg.get("graph_policy", "legacy") not in {"legacy", "scenario_v1"}:
        fail("GRAPH_POLICY_CONFIG", "Unknown graph policy", fatal=True)
    if cfg.get("document_policy", "legacy") not in {"legacy", "purpose_v1", "purpose_v2", "prose_v1", "prose_v2"}:
        fail("DOCUMENT_POLICY_CONFIG", "Unknown document policy", fatal=True)
    if cfg.get('review_evidence_policy','quoted') not in {'quoted','sentence_ids'}:
        fail('REVIEW_EVIDENCE_POLICY','Unknown reviewer evidence policy',fatal=True)
    policy = cfg.get("relation_coverage",{})
    if any(r not in RELATION_TYPES for r in policy.get("required_types",RELATION_TYPES)) or len(set(policy.get("required_types",RELATION_TYPES))) != len(policy.get("required_types",RELATION_TYPES)):
        fail("COVERAGE_CONFIG","Unknown/duplicate required relation type",fatal=True)
    for k in ("min_accepted_per_type","max_required_per_document","max_supplemental_slots"):
        if k in policy and (not isinstance(policy[k],int) or policy[k] < (0 if k == "max_supplemental_slots" else 1)):
            fail("COVERAGE_CONFIG",k,fatal=True)
    if cfg.get("privacy_policy_version") != POLICY["version"]:
        fail("PRIVACY_POLICY_VERSION","All stages must use the same current privacy definition",fatal=True)
    if not 0 < cfg["content_jaccard_threshold"] <= 1:
        fail("RANGE_CONFIG", "content_jaccard_threshold must be in (0,1]", fatal=True)
    for domain in cfg["domains"]:
        subtypes = CATALOG["domains"][domain]
        override = cfg["selection"].get("subtype")
        if override and override not in subtypes:
            fail("SUBTYPE_SELECTION", f"{override} is not valid in {domain}", fatal=True)
        variant = cfg["selection"].get("variant")
        scenario=cfg['selection'].get('scenario')
        if scenario:
            from ..document_specs import SCENARIOS
            if not override or scenario not in {s[0] for s in SCENARIOS.get(override,[])}:
                fail('SPEC_SCENARIO','Select a subtype and one of its supported scenarios','STOP_RUN',True)
            if cfg.get('spec_policy')!='type_specs_v1':
                fail('SPEC_SCENARIO','Scenario selection requires type_specs_v1','STOP_RUN',True)
        for subtype in ([override] if override else subtypes):
            allowed_variants=['type_spec'] if cfg.get('spec_policy')=='type_specs_v1' else format_for(domain, subtype)[2]
            if variant and variant not in allowed_variants:
                fail("VARIANT_SELECTION", f"{variant} is incompatible with {domain}/{subtype}", fatal=True)
            reference=cfg['selection'].get('reference_profile') or cfg.get('reference_profile')
            if reference:
                from ..reference_people import PROFILES, SUPPORTED
                if reference not in PROFILES or domain!='career_education' or subtype not in SUPPORTED:
                    fail('REFERENCE_SELECTION','Select a registered reference profile and a supported career/education narrative subtype',fatal=True)
    rows = read_json(Path(cfg["pool_path"]))
    if not rows or not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows) or any(t not in rows[0] for t in TYPES):
        fail("POOL_SCHEMA", "Pool must contain every declared type", fatal=True)
    cfg["resource_hashes"] = resource_hashes(cfg)
    cfg["config_hash"] = digest(cfg)
    run_dir = ROOT / "runs" / run_id
    path = run_dir / "run_config.json"
    if path.exists():
        old = read_json(path)
        if old["config_hash"] != cfg["config_hash"]:
            fail("RUN_VERSION_MISMATCH", "Configuration/resources/code changed; use a new run ID", fatal=True)
        return Store(run_dir)
    store = Store(run_dir)
    rng = random.Random(cfg["seed"])
    for domain in cfg["domains"]:
        subtypes = list(CATALOG["domains"][domain])
        override = cfg["selection"].get("subtype")
        if override:
            if override not in subtypes:
                fail("SUBTYPE_SELECTION", f"{override} is not valid in {domain}", fatal=True)
            subtypes = [override]
        rng.shuffle(subtypes)
        for index in range(cfg["target_per_domain"]):
            store.execute("INSERT INTO slots(slot_id,domain,subtype) VALUES(?,?,?)", (f"{domain}_{index+1:03d}", domain, subtypes[index % len(subtypes)]))
    atomic_json(path, {**cfg, "created_at": now()})
    atomic_json(run_dir / "format_catalog.json", format_catalog())
    if cfg.get('spec_policy')=='type_specs_v1':
        from ..document_specs import DEFINITIONS, SCENARIOS, UPSTREAM
        atomic_json(run_dir/'document_specs.json',{'upstream_commit':UPSTREAM,
            'definitions':{d:{s:DEFINITIONS[d,s] for s in CATALOG['domains'][d]} for d in cfg['domains']},
            'scenarios':SCENARIOS})
    atomic_json(run_dir / "allowed_triples_by_domain.json", {d: allowed_triples(d) for d in cfg["domains"]})
    atomic_json(run_dir/"privacy_policy.json",{**POLICY,"hash":POLICY_HASH})
    atomic_json(run_dir/"person_catalog.json",{d:{s:{"person_count_range":party_range(d,s),"roles":role_ids(d,s)} for s in CATALOG["domains"][d]} for d in cfg["domains"]})
    atomic_json(run_dir/"coverage_preflight.json",{"required_types":policy.get("required_types",RELATION_TYPES),
        "unreachable_types":[r for r in policy.get("required_types",RELATION_TYPES) if not eligible_targets(cfg,r)],
        "basis":"Selected domains/subtypes and person/type capacity; generation budgets and semantic acceptance are not guaranteed."})
    store.event(None, 0, "prepared", {"domains": cfg["domains"], "target_per_domain": cfg["target_per_domain"], "pool_rows": len(rows), "mode": mode})
    store.manifest()
    return store
