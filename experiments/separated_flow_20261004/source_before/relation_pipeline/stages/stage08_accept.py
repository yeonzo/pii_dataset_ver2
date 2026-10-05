"""Input: reviewed text/graph. Output: original augmented schema and commit audit."""
from __future__ import annotations

import json
from pathlib import Path

from ..common import ROOT, atomic_json, fail, file_hash, now
from .stage02_plan import privacy_groups
from ..validation import validate_document
from ..coverage import index_final_relations
from ..privacy import POLICY_HASH


def annotate(filled: dict, plan: dict, document_id: str = "DOCUMENT") -> dict:
    groups = privacy_groups(plan)
    sent_indices = {s["sent_idx"]: f"{document_id}_{i}" for i,s in enumerate(filled["sentences"])}
    entities = [{"entity_id":e["entity_id"],"entity_type":e["entity_type"],"canonical_form":e["canonical_form"],"mentions":[{**{k:m[k] for k in ("form","begin","end")}, "sent_idx": sent_indices[m["sent_idx"]]} for m in e["mentions"]]} for e in filled["entities"]]
    sentences = []
    for s in filled["sentences"]:
        text = s["sentence"]
        spans = []
        occupied = set()
        for e in entities:
            for m in e["mentions"]:
                if m["sent_idx"] != sent_indices[s["sent_idx"]]:
                    continue
                begin,end = m["begin"],m["end"]
                if not 0 <= begin < end <= len(text) or text[begin:end] != m["form"]:
                    fail("ANNOTATION_SPAN", e["entity_id"], "CODE_FIX", True)
                positions = set(range(begin,end))
                if occupied & positions:
                    fail("ANNOTATION_OVERLAP", e["entity_id"], "CODE_FIX", True)
                occupied |= positions
                if groups[e["entity_id"]] == "PII":
                    spans.append({"form":m["form"],"label":e["entity_type"],"begin":begin,"end":end})
        spans.sort(key=lambda m:m["begin"])
        bio = ["O"]*len(text)
        for i,span in enumerate(spans):
            span["id"] = i
            bio[span["begin"]] = "B-"+span["label"]
            for j in range(span["begin"]+1,span["end"]):
                bio[j] = "I-"+span["label"]
        sentences.append({"sent_idx":sent_indices[s["sent_idx"]],"sentence":text,"PII_set":spans,"sent_seq":list(text),"labelling_seq":bio})
    by_id = {e["entity_id"]:e["entity_type"] for e in entities}
    relations = [{"entity":r["source"],"entity_type":by_id[r["source"]],"target_entity":r["target"],"target_entity_type":by_id[r["target"]],"relation":r["relation"],"privacy_label":r["target_privacy"]} for r in plan["relations"]]
    return {"sentences":sentences,"entities":entities,"relations":relations}


def commit(store, cfg: dict, condition: dict, plan: dict, filled: dict, review: dict, checks: dict, dedup) -> dict:
    candidate,slot = condition["candidate_id"],condition["slot_id"]
    if not checks["passed"]:
        fail("UNREVIEWED_COMMIT", "All review gates must pass", "CODE_FIX", True)
    existing = store.rows("SELECT * FROM accepted WHERE candidate_id=?",(candidate,))
    if existing:
        return existing[0]
    if store.db.execute("SELECT status FROM slots WHERE slot_id=?",(slot,)).fetchone()[0] == "accepted":
        fail("SLOT_COMMIT_CONFLICT", slot, "STOP_CANDIDATE")
    dedup.plan_check(plan["plan_fingerprint"],candidate,plan)
    diversity = dedup.document_check(filled,condition,candidate)
    document_id = cfg["run_id"]+"_"+slot
    doc = annotate(filled,plan,document_id)
    validate_document(doc)
    output = ROOT/"output"/cfg["run_id"]/"dataset"/condition["domain"]/(document_id+".json")
    atomic_json(output,doc)
    sha = file_hash(output)
    record = {"candidate_id":candidate,"slot_id":slot,"document_id":document_id,"document_path":str(output),"document_sha256":sha,"plan_fingerprint":plan["plan_fingerprint"],"structure_fingerprint":diversity["structure"]["fingerprint"],"normalized_text":diversity["normalized_text"],"metrics":checks["distribution"],"created_at":now()}
    audit = {**record,"schema_version":cfg["schema_version"],"privacy_policy_version":cfg["privacy_policy_version"],"privacy_policy_hash":POLICY_HASH,"person_plan":plan.get("persons",[]),"person_entity_links":plan.get("person_entity_links",[]),"observed_persons":review.get("person_checks",{}),"models":{"generation":cfg["generation_model"],"review":cfg["review_model"]},"quality":review["quality"],"review_passed":True,"annotation_passed":True,"mode":cfg["mode"]}
    if condition.get('reference_profile'):
        from ..reference_people import PROFILES
        audit['reference_profile']={'profile_id':condition['reference_profile'],**PROFILES[condition['reference_profile']]}
    audit['evidence_quote_source']='code_from_reviewer_sentence_ids' if condition.get('review_evidence_policy')=='sentence_ids' else 'model_verbatim_quotes'
    atomic_json(store.run_dir/"audits"/(candidate+".json"),audit)
    with store.db:
        store.db.execute("INSERT INTO accepted(candidate_id,slot_id,document_id,document_path,document_sha256,plan_fingerprint,structure_fingerprint,normalized_text,metrics,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",tuple(record[k] if k != "metrics" else json.dumps(record[k],ensure_ascii=False) for k in ("candidate_id","slot_id","document_id","document_path","document_sha256","plan_fingerprint","structure_fingerprint","normalized_text","metrics","created_at")))
        store.db.execute("UPDATE slots SET status='accepted',candidate_id=?,document_id=? WHERE slot_id=?",(candidate,document_id,slot))
        store.db.execute("UPDATE candidates SET status='accepted',finished_at=?,final_stage=8 WHERE candidate_id=?",(now(),candidate))
        index_final_relations(store,candidate,doc,sha)
    store.manifest()
    return {"document_id":document_id,"document_path":str(output),"document_sha256":sha,"accepted":True}
