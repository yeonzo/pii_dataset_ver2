"""Strict JSON contracts, used both by Responses API and local validation."""
from __future__ import annotations

import re

from .common import TYPES, StageFailure, fail


def string(enum=None):
    result = {"type": "string"}
    if enum is not None:
        result["enum"] = list(enum)
    return result


def array(items):
    return {"type": "array", "items": items}


def obj(**properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


INT = {"type": "integer"}
BOOL = {"type": "boolean"}
TEXT = string()
GROUPS = array(array(TEXT))
KINDS = ("prose", "key_value", "question", "answer", "list_item", "numbered_list", "heading")
ENTITY = obj(entity_id=TEXT, entity_type=string(TYPES), context_role=TEXT, slot_group=TEXT)
RELATION = obj(relation_id=TEXT, source=TEXT, target=TEXT, relation=TEXT, target_privacy=string(("PII", "NON_PII")), context_reason=TEXT, scene_id=TEXT)
SCENE = obj(scene_id=TEXT, section_id=TEXT, order=INT, purpose=TEXT, relation_ids=array(TEXT), outline=TEXT)
CONSTRAINT = obj(constraint_id=TEXT, kind=string(("same_persona", "same_organization", "occupation", "distinct_value")), entity_ids=array(TEXT), field=TEXT, allowed_values=array(TEXT))
PERSON = obj(person_id=TEXT,name_entity_id=TEXT,role=TEXT,context_kind=string(("actual_party","example_person","public_reference")))
PERSON_LINK = obj(person_id=TEXT,entity_id=TEXT,role=TEXT,link_kind=string(("identity","personal_attribute","related_context")),relation_ids=array(TEXT))
PLAN = obj(plan_version=INT, entities=array(ENTITY), relations=array(RELATION), scenes=array(SCENE), slot_constraints=array(CONSTRAINT),persons=array(PERSON),person_entity_links=array(PERSON_LINK))
SEGMENT = obj(sentence_id=TEXT, section_id=TEXT, scene_id=TEXT, kind=string(KINDS), text=TEXT)
REF = obj(ref_id=TEXT, entity_id=TEXT, surface=TEXT, kind=string(("role", "demonstrative")))
EVIDENCE = obj(relation_id=TEXT, evidence_groups=GROUPS)
DRAFT = obj(draft_version=INT, segments=array(SEGMENT), refs=array(REF), relation_evidence=array(EVIDENCE))
PATCH = obj(base_draft_version=INT, insertions=array(obj(after_sentence_id=TEXT, segments=array(SEGMENT))), replacements=array(SEGMENT), refs=array(REF), relation_evidence_updates=array(EVIDENCE))
QUOTES = array(obj(sentence_id=TEXT, quote=TEXT))
CHECK = obj(relation_id=TEXT, extractable=BOOL, observed_privacy=string(("PII", "NON_PII", "AMBIGUOUS")), direction_supported=BOOL, evidence_groups=GROUPS, evidence_quotes=QUOTES, coreference_unambiguous=BOOL, single_sentence_sufficient=BOOL, reason=TEXT)
REF_CHECK = obj(ref_id=TEXT, observed_entity_id={"type": ["string", "null"]}, unambiguous=BOOL, evidence_groups=GROUPS, evidence_quotes=QUOTES, reason=TEXT)
GRADE = string(("상", "중", "하"))
QUALITY = obj(overall=GRADE, scores=obj(consistency=GRADE, fluency=GRADE, suitability=GRADE), reason=TEXT)
REVIEW = obj(relation_checks=array(CHECK), reference_checks=array(REF_CHECK), missing_relations=array(obj(source=TEXT, target=TEXT, relation=TEXT, observed_privacy=string(("PII", "NON_PII", "AMBIGUOUS")), evidence_groups=GROUPS, evidence_quotes=QUOTES)), unregistered_entities=array(obj(entity_type=TEXT, sentence_id=TEXT, form=TEXT, reason=TEXT)), contradictions=array(obj(sentence_ids=array(TEXT), reason=TEXT)), format_adherence=obj(document_format_supported=BOOL, layout_variant_supported=BOOL, viewpoint_supported=BOOL, section_roles_supported=BOOL, reason=TEXT), quality=QUALITY)
REVIEW["properties"]["person_checks"] = obj(actual_person_count=INT,observed_persons=array(obj(name_entity_id=TEXT,role=TEXT,context_kind=string(("actual_party","example_person","public_reference")),evidence_groups=GROUPS,evidence_quotes=QUOTES)),reason=TEXT)
REVIEW["properties"]["text_issues"] = array(obj(kind=string(("fluency","consistency","format")),sentence_ids=array(TEXT),relation_ids=array(TEXT),reason=TEXT,fix_instruction=TEXT))
REVIEW["required"] = list(REVIEW["properties"])
PRIVACY_ONLY_CHECK = obj(relation_id=TEXT, relation_supported=BOOL,
    direction_supported=BOOL, attribution_supported=BOOL,
    observed_privacy=string(("PII", "NON_PII", "AMBIGUOUS")), reason=TEXT)
PRIVACY_ONLY_REVIEW = obj(
    relation_checks=array(PRIVACY_ONLY_CHECK),
    unplanned_relations=array(obj(source=TEXT,target=TEXT,relation=TEXT,
        observed_privacy=string(("PII","NON_PII","AMBIGUOUS")),reason=TEXT)),
    format_adherence=obj(document_format_supported=BOOL,layout_variant_supported=BOOL,
        viewpoint_supported=BOOL,section_roles_supported=BOOL,reason=TEXT),
    quality=QUALITY,
    text_issues=array(obj(kind=string(("fluency","consistency","format")),
        sentence_ids=array(TEXT),relation_ids=array(TEXT),reason=TEXT,fix_instruction=TEXT)))


def validate(data, schema, path="$"):
    if "anyOf" in schema:
        for branch in schema["anyOf"]:
            try:
                validate(data, branch, path)
                return
            except StageFailure:
                continue
        fail("SCHEMA_ANY_OF", path + ": no allowed relation slot matched", "RETRY_RESPONSE")
    t = schema["type"]
    allowed = t if isinstance(t, list) else [t]
    actual = "null" if data is None else "boolean" if isinstance(data, bool) else "integer" if isinstance(data, int) else "string" if isinstance(data, str) else "array" if isinstance(data, list) else "object" if isinstance(data, dict) else "unknown"
    if actual not in allowed or ("enum" in schema and data not in schema["enum"]):
        fail("SCHEMA_TYPE", f"{path}: expected {schema.get('enum', allowed)}, got {actual}", "RETRY_RESPONSE")
    if actual == "string" and "pattern" in schema and not re.fullmatch(schema["pattern"], data):
        fail("SCHEMA_PATTERN", path + ": unsupported ID", "RETRY_RESPONSE")
    if actual == "object":
        props = schema["properties"]
        if set(data) != set(props):
            fail("SCHEMA_KEYS", f"{path}: missing={sorted(set(props)-set(data))}, extra={sorted(set(data)-set(props))}", "RETRY_RESPONSE")
        for key, value in data.items():
            validate(value, props[key], f"{path}.{key}")
    elif actual == "array":
        if len(data) < schema.get("minItems", 0) or ("maxItems" in schema and len(data) > schema["maxItems"]):
            fail("SCHEMA_ARRAY_LENGTH", f"{path}: got {len(data)}, expected {schema.get('minItems',0)}..{schema.get('maxItems','unbounded')}", "RETRY_RESPONSE")
        for i, value in enumerate(data):
            validate(value, schema["items"], f"{path}[{i}]")
