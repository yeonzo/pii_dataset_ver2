"""Accepted-only dedup registry plus the frozen reference corpus."""
from __future__ import annotations

import collections
import json
import re
import zipfile
from pathlib import Path

from .common import Issue, StageFailure, digest, read_json


def normalized_text(doc: dict) -> str:
    mentions = collections.defaultdict(list)
    for e in doc["entities"]:
        for m in e["mentions"]:
            mentions[str(m["sent_idx"])].append((m["begin"],m["end"],e["entity_type"]))
    parts = []
    for s in doc["sentences"]:
        text = s["sentence"]
        cursor, pieces = 0, []
        for begin,end,type_ in sorted(set(mentions[str(s["sent_idx"])])):
            if begin < cursor or not 0 <= begin < end <= len(text):
                raise ValueError("Invalid source mention offsets for dedup normalization")
            pieces.extend([text[cursor:begin], "<"+type_+">"])
            cursor = end
        pieces.append(text[cursor:])
        parts.append("".join(pieces))
    return re.sub(r"\s+", " ", "\n".join(parts)).strip()


def grams(text: str) -> set[str]:
    return {text[i:i+4] for i in range(max(0,len(text)-3))}


def jaccard(a: set, b: set) -> float:
    intersection = len(a & b)
    return intersection / (len(a)+len(b)-intersection) if a or b else 1.0


def structure_fingerprint(filled: dict) -> str:
    blocks = []
    for s in filled["sentences"]:
        if not blocks or blocks[-1]["section"] != s["section_id"]:
            # Abstract section identity: compare the actual ordered blocks, not assigned IDs.
            blocks.append({"section": s["section_id"], "kinds": [], "lengths": []})
        blocks[-1]["kinds"].append(s["kind"])
        blocks[-1]["lengths"].append(len(s["sentence"]))
    actual = [{"segment_count":len(b["kinds"]), "kind_runs":[(k,len(list(g))) for k,g in __import__('itertools').groupby(b["kinds"])], "mean_length_bin": sum(b["lengths"])//max(1,len(b["lengths"]))//40} for b in blocks]
    return digest({"blocks": actual, "first_kind": filled["sentences"][0]["kind"], "last_kind": filled["sentences"][-1]["kind"]})


class Dedup:
    def __init__(self, cfg: dict, store):
        self.cfg, self.store = cfg, store
        self.reference = []
        path = cfg.get("reference_dataset")
        if path:
            with zipfile.ZipFile(path) as archive:
                for name in archive.namelist():
                    if name.endswith(".json"):
                        doc = json.loads(archive.read(name))
                        text = normalized_text(doc)
                        self.reference.append(("reference:"+name, grams(text)))

    def plan_check(self, fingerprint: str, candidate: str, plan=None) -> dict:
        count = self.store.db.execute("SELECT COUNT(*) FROM accepted WHERE plan_fingerprint=? AND candidate_id<>?", (fingerprint,candidate)).fetchone()[0]
        passed = count < self.cfg["max_identical_plan_fingerprint"]
        result = {"fingerprint": fingerprint, "accepted_identical_before": count, "limit": self.cfg["max_identical_plan_fingerprint"], "passed": passed, "continuous_similarity_used_for_rejection": False}
        result["max_relation_feature_jaccard"] = None
        result["nearest_plan_document_id"] = None
        if plan is not None:
            def features(graph):
                types = {e["entity_id"]:e["entity_type"] for e in graph["entities"]}
                return {(types[r["source"]],r["relation"],types[r["target"]]) for r in graph["relations"]}
            own = features(plan)
            best = 0.0
            for row in self.store.rows("SELECT candidate_id,document_id FROM accepted WHERE candidate_id<>?", (candidate,)):
                path = self.store.run_dir/"candidates"/row["candidate_id"]/"plan.json"
                if path.is_file():
                    score = jaccard(own,features(read_json(path)))
                    if score > best:
                        best = score
                        result["nearest_plan_document_id"] = row["document_id"]
            result["max_relation_feature_jaccard"] = best
        if not passed:
            raise StageFailure([Issue("PLAN_DUPLICATE", f"Identical plan count {count} reached cap", "NEW_CANDIDATE")])
        return result

    def document_check(self, filled: dict, condition: dict, candidate: str) -> dict:
        text = normalized_text(filled)
        features = grams(text)
        best, nearest = 0.0, None
        accepted = self.store.rows("SELECT candidate_id,document_id,normalized_text FROM accepted WHERE candidate_id<>?", (candidate,))
        for document_id, other in self.reference + [(r["document_id"],grams(r["normalized_text"])) for r in accepted]:
            score = jaccard(features,other)
            if score > best:
                best,nearest = score,document_id
        structure = structure_fingerprint(filled)
        structure_count = self.store.db.execute("SELECT COUNT(*) FROM accepted a JOIN candidates c ON c.candidate_id=a.candidate_id WHERE a.structure_fingerprint=? AND c.document_format=? AND a.candidate_id<>?", (structure,condition["document_format"],candidate)).fetchone()[0]
        issues = []
        if best >= self.cfg["content_jaccard_threshold"]:
            issues.append(Issue("CONTENT_DUPLICATE", f"Normalized 4-gram similarity={best:.4f}, nearest={nearest}", "NEW_CANDIDATE"))
        structure_passed = condition["fixed_format"] or structure_count < self.cfg["max_identical_structure_fingerprint"]
        if not structure_passed:
            issues.append(Issue("STRUCTURE_DUPLICATE", f"Actual structure repeated {structure_count} times", "NEW_CANDIDATE"))
        result = {"normalized_text":text, "content":{"max_jaccard":best,"nearest_document_id":nearest,"threshold":self.cfg["content_jaccard_threshold"],"passed":best<self.cfg["content_jaccard_threshold"]}, "structure":{"fingerprint":structure,"accepted_identical_before":structure_count,"limit":self.cfg["max_identical_structure_fingerprint"],"fixed_format_exempt":condition["fixed_format"],"passed":structure_passed},"passed":not issues}
        if issues:
            failure = StageFailure(issues)
            failure.metrics = result
            raise failure
        return result
