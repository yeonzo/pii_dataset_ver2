"""Coverage is measured on committed final relations, never plans or retries."""
from __future__ import annotations

import collections
import json
from pathlib import Path

from .common import read_json
from .formats import CATALOG, ONTOLOGY, allowed_triples
from .persons import party_range
from .semantic_profiles import profile_for

RELATION_TYPES = sorted({r["relation"] for items in ONTOLOGY.values() for r in items})


def index_final_relations(store,candidate,document,sha):
    for i,r in enumerate(document["relations"],1):
        store.db.execute("INSERT OR REPLACE INTO accepted_relations(candidate_id,relation_id,relation,privacy_label,source,target,document_sha256) VALUES(?,?,?,?,?,?,?)",
            (candidate,f"R{i}",r["relation"],r["privacy_label"],r["entity"],r["target_entity"],sha))


def final_relation_rows(store,domain=None):
    rows = store.rows("SELECT r.*,c.domain,c.subtype,a.document_id FROM accepted_relations r JOIN accepted a ON a.candidate_id=r.candidate_id AND a.document_sha256=r.document_sha256 JOIN candidates c ON c.candidate_id=a.candidate_id" + (" WHERE c.domain=?" if domain else ""),(domain,) if domain else ())
    indexed = {r["candidate_id"] for r in rows}
    # Read-only historical fallback: old runs did not have the committed index.
    for a in store.rows("SELECT a.*,c.domain,c.subtype FROM accepted a JOIN candidates c ON c.candidate_id=a.candidate_id" + (" WHERE c.domain=?" if domain else ""),(domain,) if domain else ()):
        if a["candidate_id"] in indexed:
            continue
        doc = read_json(Path(a["document_path"]))
        rows.extend({"candidate_id":a["candidate_id"],"relation_id":f"R{i}","relation":r["relation"],"privacy_label":r["privacy_label"],
            "source":r["entity"],"target":r["target_entity"],"domain":a["domain"],"subtype":a["subtype"],
            "document_id":a["document_id"],"document_sha256":a["document_sha256"]} for i,r in enumerate(doc["relations"],1))
    return rows


def coverage_state(store,cfg,domain=None):
    rows = final_relation_rows(store,domain)
    counts = collections.Counter(r["relation"] for r in rows)
    labels = collections.Counter((r["relation"],r["privacy_label"]) for r in rows)
    docs = collections.defaultdict(set)
    for r in rows:
        docs[r["relation"]].add(r["candidate_id"])
    policy = cfg.get("relation_coverage",{})
    required = policy.get("required_types",RELATION_TYPES)
    minimum = policy.get("min_accepted_per_type",1)
    missing = [r for r in required if counts[r] < minimum]
    return {"enabled":policy.get("enabled",False),"scope":"run" if domain is None else domain,
        "required_types":required,"minimum_per_type":minimum,"required_type_count":len(required),
        "covered_type_count":len(required)-len(missing),"complete":not missing,"missing_types":missing,
        "basis":"Committed final relation rows only; each document counted once, independent of planned/review retry counts.",
        "counts":[{"relation":r,"accepted_relations":counts[r],"accepted_documents":len(docs[r]),
            "PII":labels[r,"PII"],"NON_PII":labels[r,"NON_PII"],"required_minimum":minimum if r in required else 0,
            "requirement_met":counts[r] >= minimum if r in required else True} for r in RELATION_TYPES]}


def completion_state(store,cfg):
    slots = store.rows("SELECT s.* FROM slots s LEFT JOIN coverage_slots x ON x.slot_id=s.slot_id WHERE x.slot_id IS NULL")
    quota = bool(slots) and all(s["status"] == "accepted" for s in slots)
    coverage = coverage_state(store,cfg)
    return {"quota_complete":quota,"coverage_complete":coverage["complete"],
        "complete":quota and (not coverage["enabled"] or coverage["complete"]),"relation_coverage":coverage}


def candidate_triples(condition,privacy):
    from .document_specs import compatible_relation
    personal = set(condition["allowed_personal_types"])|{"NAME"}
    public = set(condition["allowed_public_types"])
    n = condition.get("n_parties",1)
    triples = []
    for s,r,t in allowed_triples(condition["domain"]):
        if not compatible_relation(condition,s,r,t):continue
        if privacy == "PII" and s == "NAME" and t in personal and (t != "NAME" or n>=2):
            triples.append([s,r,t])
        if privacy == "NON_PII" and s in {"WORKPLACE","DEPARTMENT","SCHOOL"}&public and t in public:
            triples.append([s,r,t])
    profile = profile_for(condition)
    if profile is None:
        return triples
    available = {tuple(t) for t in triples}
    return [list(t) for t in profile[privacy] if t in available]


def select_required(store,cfg,condition,forced=None):
    policy = cfg.get("relation_coverage",{})
    if not policy.get("enabled") and not forced:
        return []
    state = coverage_state(store,cfg)
    counts = {r["relation"]:r["accepted_relations"] for r in state["counts"]}
    wanted = list(forced) if forced else sorted(state["missing_types"],key=lambda r:(counts[r],r))
    capacity = {"PII":condition["pii_relation_target"],"NON_PII":condition["non_pii_relation_target"]}
    options = {label:candidate_triples(condition,label) for label in capacity}
    chosen = []
    for relation in wanted:
        labels = [label for label in capacity if capacity[label] and any(t[1] == relation for t in options[label])]
        if condition.get("n_parties",1)>capacity["PII"] and "PII" in labels:
            # A low-budget multi-person plan needs a NAME→NAME personal edge.
            labels = [label for label in labels if label != "PII" or any(t[1] == relation and t[2] == "NAME" for t in options[label])]
        if not labels:
            continue
        label = "NON_PII" if "NON_PII" in labels else labels[0]
        chosen.append({"relation":relation,"privacy":label})
        capacity[label] -= 1
        if len(chosen) >= policy.get("max_required_per_document",3):
            break
    return chosen


def eligible_targets(cfg,relation):
    result = []
    for domain in cfg["domains"]:
        for subtype,info in CATALOG["domains"][domain].items():
            if cfg.get("selection",{}).get("subtype") not in (None,subtype):
                continue
            _,hi = party_range(domain,subtype)
            condition = {"domain":domain,"allowed_personal_types":info["personal_types"],
                "allowed_public_types":["WORKPLACE","DEPARTMENT","SCHOOL","POSITION","MAJOR","ADDRESS","EMAIL","TELEPHONE","MOBILE_PHONE","BANK_ACCOUNT_NUMBER"],"n_parties":hi}
            condition.update(subtype=subtype,graph_policy=cfg.get("graph_policy","legacy"),spec_policy=cfg.get('spec_policy','legacy'))
            if any(t[1] == relation for label in ("PII","NON_PII") for t in candidate_triples(condition,label)):
                result.append((domain,subtype))
    return result


def next_coverage_slot(store,cfg):
    policy = cfg.get("relation_coverage",{})
    if not policy.get("enabled"):
        return None
    state = coverage_state(store,cfg)
    count = store.db.execute("SELECT COUNT(*) FROM coverage_slots").fetchone()[0]
    if not state["missing_types"] or count >= policy.get("max_supplemental_slots",38):
        return None
    totals = {r["domain"]:r["n"] for r in store.rows("SELECT domain,COUNT(*) n FROM candidates GROUP BY domain")}
    for relation in state["missing_types"]:
        targets = [(d,s) for d,s in eligible_targets(cfg,relation) if totals.get(d,0)<cfg["max_candidates_per_domain"]]
        if not targets:
            continue
        domain,subtype = min(targets,key=lambda ds:(totals.get(ds[0],0),ds))
        slot = {"slot_id":f"{domain}_coverage_{count+1:03d}","domain":domain,"subtype":subtype}
        store.execute("INSERT INTO slots(slot_id,domain,subtype) VALUES(?,?,?)",tuple(slot.values()))
        store.execute("INSERT INTO coverage_slots(slot_id,required_types) VALUES(?,?)",(slot["slot_id"],json.dumps([relation])))
        store.event(None,1,"coverage_slot_added",{**slot,"required_types":[relation]})
        return slot
