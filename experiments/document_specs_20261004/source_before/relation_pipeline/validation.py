"""Independent validation of the final, legacy-compatible augmented schema."""
from __future__ import annotations

import collections
import re

from .common import TYPES, Issue, StageFailure


def validate_document(doc: dict) -> dict:
    issues = []
    if not isinstance(doc, dict) or set(doc) != {"sentences", "entities", "relations"}:
        raise StageFailure([Issue("FINAL_SCHEMA", "Expected sentences/entities/relations", "CODE_FIX")])
    if any(not isinstance(doc[k], list) for k in doc) or not doc["sentences"]:
        raise StageFailure([Issue("FINAL_LISTS", "Nonempty sentence list and entity/relation lists required", "CODE_FIX")])
    sentences = {}
    prefix = None
    for i, sentence in enumerate(doc["sentences"]):
        required = {"sent_idx", "sentence", "PII_set", "sent_seq", "labelling_seq"}
        if not isinstance(sentence, dict) or not required <= sentence.keys():
            issues.append(Issue("FINAL_SENTENCE_SCHEMA", f"Sentence {i}", "CODE_FIX"))
            continue
        sid, text = sentence["sent_idx"], sentence["sentence"]
        if not isinstance(sid, str) or not isinstance(text, str):
            issues.append(Issue("FINAL_SENTENCE_TYPES", f"Sentence {i}: string index/text required", "CODE_FIX"))
            continue
        match = re.fullmatch(r"(.+)_(\d+)", sid)
        if not match or int(match[2]) != i or (prefix is not None and match[1] != prefix) or sid in sentences:
            issues.append(Issue("FINAL_SENTENCE_INDEX", sid, "CODE_FIX"))
        if match:
            prefix = match[1] if prefix is None else prefix
        sentences[sid] = sentence
        if sentence["sent_seq"] != list(text):
            issues.append(Issue("FINAL_CHAR_SEQUENCE", sid, "CODE_FIX"))
        if re.search(r"<(?:[A-Z][A-Z0-9_]*:E\d+|REF:C\d+)>|\{josa:", text):
            issues.append(Issue("FINAL_PLACEHOLDER", sid, "CODE_FIX"))
        expected_bio = ["O"] * len(text)
        previous_end = 0
        for j, span in enumerate(sentence["PII_set"]):
            begin, end = span.get("begin"), span.get("end")
            if (type(begin) is not int or type(end) is not int or not 0 <= begin < end <= len(text)
                    or begin < previous_end or text[begin:end] != span.get("form")
                    or span.get("label") not in TYPES or span.get("id") != j):
                issues.append(Issue("FINAL_PII_SPAN", sid, "CODE_FIX"))
                continue
            previous_end = end
            expected_bio[begin] = "B-" + span["label"]
            expected_bio[begin+1:end] = ["I-" + span["label"]] * (end-begin-1)
        if sentence["labelling_seq"] != expected_bio:
            issues.append(Issue("FINAL_BIO", sid, "CODE_FIX"))
    entities = {}
    occupied = collections.defaultdict(set)
    for entity in doc["entities"]:
        if not isinstance(entity, dict) or not {"entity_id", "entity_type", "canonical_form", "mentions"} <= entity.keys():
            issues.append(Issue("FINAL_ENTITY_SCHEMA", "Missing entity fields", "CODE_FIX"))
            continue
        eid = entity["entity_id"]
        if eid in entities or not re.fullmatch(r"E[1-9][0-9]*", eid) or entity["entity_type"] not in TYPES:
            issues.append(Issue("FINAL_ENTITY_ID_TYPE", eid, "CODE_FIX"))
        entities[eid] = entity
        if not isinstance(entity["canonical_form"], str) or not entity["canonical_form"].strip() or not entity["mentions"]:
            issues.append(Issue("FINAL_EMPTY_ENTITY", eid, "CODE_FIX"))
        for mention in entity["mentions"]:
            sid = mention.get("sent_idx")
            begin, end = mention.get("begin"), mention.get("end")
            sentence = sentences.get(sid)
            if (sentence is None or type(begin) is not int or type(end) is not int
                    or not 0 <= begin < end <= len(sentence["sentence"])
                    or sentence["sentence"][begin:end] != mention.get("form")):
                issues.append(Issue("FINAL_MENTION_SPAN", eid, "CODE_FIX"))
                continue
            positions = set(range(begin, end))
            if occupied[sid] & positions:
                issues.append(Issue("FINAL_MENTION_OVERLAP", eid, "CODE_FIX"))
            occupied[sid].update(positions)
    incident = collections.defaultdict(list)
    edges = set()
    for relation in doc["relations"]:
        required = {"entity", "target_entity", "entity_type", "target_entity_type", "relation", "privacy_label"}
        if not isinstance(relation, dict) or not required <= relation.keys():
            issues.append(Issue("FINAL_RELATION_SCHEMA", "Missing relation fields", "CODE_FIX"))
            continue
        source, target = relation["entity"], relation["target_entity"]
        if (source not in entities or target not in entities or source == target
                or relation["entity_type"] != entities[source]["entity_type"]
                or relation["target_entity_type"] != entities[target]["entity_type"]
                or relation["privacy_label"] not in {"PII", "NON_PII"}):
            issues.append(Issue("FINAL_RELATION_ENDPOINT", str(source) + "/" + str(target), "CODE_FIX"))
            continue
        edge = (source, relation["relation"], target)
        if edge in edges:
            issues.append(Issue("FINAL_DUPLICATE_RELATION", str(edge), "CODE_FIX"))
        edges.add(edge)
        incident[source].append(relation["privacy_label"])
        incident[target].append(relation["privacy_label"])
    expected_spans = collections.defaultdict(set)
    for eid, entity in entities.items():
        if not incident[eid]:
            issues.append(Issue("FINAL_ISOLATED_ENTITY", eid, "CODE_FIX"))
        if "PII" in incident[eid]:
            for mention in entity["mentions"]:
                if mention.get("sent_idx") in sentences:
                    expected_spans[mention["sent_idx"]].add((mention.get("begin"), mention.get("end"), mention.get("form"), entity["entity_type"]))
    for sid, sentence in sentences.items():
        actual = {(s.get("begin"), s.get("end"), s.get("form"), s.get("label")) for s in sentence["PII_set"]}
        if actual != expected_spans[sid]:
            issues.append(Issue("FINAL_MASKING_GROUP", "PII spans must match all actual mentions of PII-incident entities: " + sid, "CODE_FIX"))
    if issues:
        raise StageFailure(issues)
    return {"passed": True, "sentences": len(sentences), "entities": len(entities), "relations": len(edges),
            "pii_mentions": sum(len(s["PII_set"]) for s in sentences.values())}
