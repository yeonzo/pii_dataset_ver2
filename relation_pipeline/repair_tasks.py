"""Explicit repair targets, unique edit contracts and measurable postconditions."""
from __future__ import annotations

import collections
import copy
import re

from .common import Issue
from .renderer import PLACEHOLDER
from .schemas import array, obj, string, validate
from .prompt_inputs import compact_issues

SEMANTIC_CODES = {"PRIVACY_AMBIGUOUS","RELATION_MEANING","REVIEW_ENDPOINT_EVIDENCE","REFERENCE_MEANING",
                  "UNPLANNED_RELATIONS","UNREGISTERED_ENTITIES","CONTRADICTIONS","FORMAT_MEANING","QUALITY_GRADE",
                  "REPAIR_BODY_UNCHANGED"}
SEMANTIC_CODES |= {"PERSON_COUNT_MEANING","PERSON_ROLE_MEANING"}
SEMANTIC_CODES |= {"TEXT_FLUENCY","TEXT_CONSISTENCY","TEXT_FORMAT"}


def actual_entities(draft, plan):
    types = {e["entity_id"]:e["entity_type"] for e in plan["entities"]}
    return {eid for s in draft["segments"] for typ,eid in PLACEHOLDER.findall(s["text"]) if types.get(eid) == typ}


def length_only(diagnosis):
    codes = {i['code'] for i in diagnosis.get('issues', [])}
    return codes == {'LENGTH_SHORTAGE'}


def normalize_sentence_ids(draft):
    """Preserve every text; do not choose among duplicate IDs for evidence."""
    result = copy.deepcopy(draft)
    seen, mapping, changes = set(), collections.defaultdict(list), []
    serial = max((int(s["sentence_id"][1:]) for s in result["segments"]
                  if re.fullmatch(r"S[1-9][0-9]*",s["sentence_id"])),default=0)+1
    for index,s in enumerate(result["segments"]):
        old = s["sentence_id"]
        if old in seen or not re.fullmatch(r"S[1-9][0-9]*",old):
            s["sentence_id"] = f"S{serial}"
            serial += 1
            changes.append({"segment_index":index,"old_id":old,"new_id":s["sentence_id"]})
        seen.add(s["sentence_id"])
        mapping[old].append(s["sentence_id"])
    for e in result["relation_evidence"]:
        if any(len(mapping.get(sid,[])) > 1 for g in e["evidence_groups"] for sid in g):
            e["evidence_groups"] = []
        else:
            e["evidence_groups"] = [[mapping.get(sid,[sid])[0] for sid in g] for g in e["evidence_groups"]]
    return result,changes


SENTENCE_END = re.compile(r"(?<!\d)[.!?。！？]+[\"'”’)]*(?:\s+|$)")


def split_prose_sentences(draft):
    """Split prose sentences/form lines, preserving words and candidate evidence."""
    result = copy.deepcopy(draft)
    if len({s["sentence_id"] for s in result["segments"]}) != len(result["segments"]) or any(
            not re.fullmatch(r"S[1-9][0-9]*",s["sentence_id"]) for s in result["segments"]):
        return result,[]
    serial = max((int(s["sentence_id"][1:]) for s in result["segments"]),default=0)+1
    mapping,segments,changes = {},[],[]
    for segment in result["segments"]:
        parts = []
        for line in segment["text"].splitlines() or [segment["text"]]:
            start = 0
            if segment["kind"] == "prose":
                for match in SENTENCE_END.finditer(line):
                    parts.append(line[start:match.end()].strip())
                    start = match.end()
            if start < len(line):
                parts.append(line[start:].strip())
        parts = [p for p in parts if p]
        if len(parts) < 2:
            segments.append(segment)
            mapping[segment["sentence_id"]] = [segment["sentence_id"]]
            continue
        identifiers = [segment["sentence_id"]]
        for part in parts[1:]:
            identifiers.append(f"S{serial}")
            serial += 1
        segments.extend({**segment,"sentence_id":sid,"text":text} for sid,text in zip(identifiers,parts))
        mapping[segment["sentence_id"]] = identifiers
        changes.append({"original_sentence_id":segment["sentence_id"],"sentence_ids":identifiers})
    result["segments"] = segments
    for e in result["relation_evidence"]:
        e["evidence_groups"] = [[part for sid in group for part in mapping.get(sid,[sid])] for group in e["evidence_groups"]]
    return result,changes


def collapse_exact_boilerplate(draft):
    """Remove verbatim copies within one scene, including repeated form rows."""
    result = copy.deepcopy(draft)
    seen,mapping,kept,merges = {},{},[],[]
    if len({s["sentence_id"] for s in result["segments"]}) != len(result["segments"]):
        return result,[]
    for segment in result["segments"]:
        key = segment["scene_id"],segment["kind"],segment["text"].strip()
        duplicate = key in seen and (segment["kind"] != "prose" or len(key[2]) >= 50
                                     or key[2] in {"감사합니다", "감사합니다."})
        if segment["kind"] != "heading" and duplicate:
            mapping[segment["sentence_id"]] = seen[key]
            merges.append({"removed_sentence_id":segment["sentence_id"],"retained_sentence_id":seen[key]})
        else:
            seen[key] = segment["sentence_id"]
            kept.append(segment)
    result["segments"] = kept
    for relation in result["relation_evidence"]:
        relation["evidence_groups"] = [list(dict.fromkeys(mapping.get(sid,sid) for sid in g)) for g in relation["evidence_groups"]]
    return result,merges


def build_tasks(draft, condition, plan, diagnosis):
    entities = {e["entity_id"]:e for e in plan["entities"]}
    relations = {r["relation_id"]:r for r in plan["relations"]}
    scenes = {s["scene_id"]:s for s in plan["scenes"]}
    missing = sorted(set(entities)-actual_entities(draft,plan))
    bad = {i.get("relation_id") for i in diagnosis["issues"] if i.get("relation_id") in relations}
    bad_entities = {i.get("entity_id") for i in diagnosis["issues"] if i.get("entity_id")}
    bad |= {r["relation_id"] for r in relations.values() if {r["source"],r["target"]}&bad_entities}
    bad |= {r["relation_id"] for r in relations.values() if {r["source"],r["target"]} & set(missing)}
    scene_ids = {relations[rid]["scene_id"] for rid in bad}
    bad_sentences = {i.get("sentence_id") for i in diagnosis["issues"] if i.get("sentence_id")}
    # A localized prose error invalidates that sentence's relationship evidence too.
    # Rebuild the affected relationships; do not protect the erroneous sentence.
    bad |= {e["relation_id"] for e in draft["relation_evidence"] if e["relation_id"] in relations
            and any(sid in bad_sentences for g in e["evidence_groups"] for sid in g)}
    scene_ids |= {relations[rid]["scene_id"] for rid in bad}
    scene_ids |= {s["scene_id"] for s in draft["segments"] if s["sentence_id"] in bad_sentences and s["scene_id"] in scenes}
    scene_ids |= {s["scene_id"] for s in scenes.values() if any(i.get("section_id") == s["section_id"] for i in diagnosis["issues"])}
    scene_ids |= set(scenes)-{s["scene_id"] for s in draft["segments"]}
    if any(not any(i.get(k) for k in ("entity_id","relation_id","sentence_id","section_id")) and i["code"] != "LENGTH_SHORTAGE" for i in diagnosis["issues"]):
        scene_ids = set(scenes)
    editable = [s["sentence_id"] for s in draft["segments"] if s["scene_id"] in scene_ids or s["sentence_id"] in bad_sentences]
    sections = condition["section_plan"]
    continuation = sorted((s["section_id"] for s in sections),key=lambda sid:diagnosis.get("metrics",{}).get("section_shortages",{}).get(sid,0),reverse=True) if any(i["code"] == "LENGTH_SHORTAGE" for i in diagnosis["issues"]) else []
    insertion_scenes = scene_ids | {s["scene_id"] for s in scenes.values() if s["section_id"] in continuation}
    affected = bad | {r["relation_id"] for r in relations.values() if r["scene_id"] in scene_ids}
    affected |= {e["relation_id"] for e in draft["relation_evidence"] if e["relation_id"] in relations
                 and any(sid in editable for g in e["evidence_groups"] for sid in g)}
    def token(eid):
        return f"<{entities[eid]['entity_type']}:{eid}>"
    tasks = {"missing_entities":[{"entity_id":eid,"placeholder":token(eid),"context_role":entities[eid]["context_role"],
                "relation_ids":[r["relation_id"] for r in plan["relations"] if eid in (r["source"],r["target"])]} for eid in missing],
        "relations":[{"relation_id":r["relation_id"],"operation":"fix" if r["relation_id"] in bad else "preserve",
            "source_placeholder":token(r["source"]),"target_placeholder":token(r["target"]),"relation":r["relation"],
            "target_privacy":r["target_privacy"],"context_reason":r["context_reason"],"scene_id":r["scene_id"],
            "section_id":scenes[r["scene_id"]]["section_id"],
            "editable_sentence_ids":[s["sentence_id"] for s in draft["segments"] if s["scene_id"] == r["scene_id"]],
            "errors":[i for i in diagnosis["issues"] if i.get("relation_id") == r["relation_id"]
                or i.get("entity_id") in (r["source"],r["target"])
                or i.get("sentence_id") in {sid for e in draft["relation_evidence"] if e["relation_id"] == r["relation_id"] for g in e["evidence_groups"] for sid in g}]}
            for r in plan["relations"] if r["relation_id"] in affected],
        "editable_sentence_ids":editable,"insertion_scene_ids":[s["scene_id"] for s in plan["scenes"] if s["scene_id"] in insertion_scenes],
        "sentence_errors":[i for i in diagnosis["issues"] if i.get("sentence_id")],
        "continuation":{"minimum_added_rendered_chars":diagnosis.get("metrics",{}).get("shortage_chars",0),"section_priority":continuation},
        "completion_conditions":["Missing entities need actual typed placeholders, not only REF.",
            "Evidence IDs must cover the exact relation endpoints/references after edits.",
            "Semantic errors need corrected text/reference meaning, not only different evidence IDs.",
            "Preserve healthy text/relations; meet minimum length after entity/relation corrections."]}
    # Reserve local edit locations without overwriting evidence for healthy relations.
    from .stages.stage05_assemble import evidence_issues
    refs = {r["ref_id"]:r for r in draft["refs"]}
    evidence = {r["relation_id"]:r["evidence_groups"] for r in draft["relation_evidence"]}
    protected = {sid for rid,groups in evidence.items() if rid in relations and rid not in bad
                 and not evidence_issues(groups,draft["segments"],(relations[rid]["source"],relations[rid]["target"]),refs)
                 for group in groups for sid in group}
    reserved = set()
    for task in tasks["relations"]:
        if task["operation"] != "fix":
            continue
        candidates = [s for s in draft["segments"] if s["scene_id"] == task["scene_id"]
                      and s["sentence_id"] not in protected|reserved and s["kind"] not in ("heading","question")]
        # Prefer the faulty relationship's current text over unrelated work records.
        candidates.sort(key=lambda s:sum(t in s["text"] for t in (task["source_placeholder"],task["target_placeholder"])),reverse=True)
        related = [s for s in candidates if task["source_placeholder"] in s["text"] or task["target_placeholder"] in s["text"]]
        replacement = related[0]["sentence_id"] if related else ""
        if replacement:
            reserved.add(replacement)
        owner_segments = [s for s in draft["segments"] if s["scene_id"] == task["scene_id"]]
        section_index = next((i for i,sec in enumerate(sections) if sec["section_id"] == task["section_id"]),0)
        preceding_sections = {sec["section_id"] for sec in sections[:section_index]}
        preceding = [s for s in draft["segments"] if s["section_id"] in preceding_sections]
        task["replacement_sentence_id"] = replacement
        task["insertion_after_sentence_id"] = replacement or (owner_segments[-1]["sentence_id"] if owner_segments else preceding[-1]["sentence_id"] if preceding else "")
    tasks["reserved_sentence_ids"] = sorted(reserved)
    tasks["protected_sentence_ids"] = sorted(protected)
    tasks["required_replacement_sentence_ids"] = sorted(bad_sentences-protected-reserved)
    global_semantic = any(i["code"] in SEMANTIC_CODES and not i.get("relation_id") for i in diagnosis["issues"])
    tasks["editable_sentence_ids"] = [sid for sid in editable if sid in bad_sentences or global_semantic]
    # Length units are characters of newly written context, never repeated filler.
    shortage = diagnosis.get("metrics",{}).get("shortage_chars",0)
    tasks["continuation_targets"] = []
    if shortage:
        costs = diagnosis.get("metrics",{}).get("sentence_chars",{})
        replacement_cost = sum(costs.get(sid,len(next(s["text"] for s in draft["segments"] if s["sentence_id"] == sid)))
                               for sid in reserved | (set(tasks["editable_sentence_ids"])-protected))
        minimum = shortage + replacement_cost
        deficits = diagnosis.get("metrics",{}).get("section_shortages",{})
        targets = [section for section in sections if deficits.get(section["section_id"],0)>0]
        if not targets:
            targets = sections[:1]
        total_weight = sum(max(1,deficits.get(s["section_id"],0)) for s in targets)
        for section in targets:
            scene = next(s for s in plan["scenes"] if s["section_id"] == section["section_id"])
            last = next((s["sentence_id"] for s in reversed(draft["segments"]) if s["scene_id"] == scene["scene_id"]),"")
            weight = max(1,deficits.get(section["section_id"],0))
            chars = (minimum*weight+total_weight-1)//total_weight
            tasks["continuation_targets"].append({"scene_id":scene["scene_id"],"section_id":section["section_id"],
                "after_sentence_id":last,"minimum_new_chars":chars})
        tasks["continuation"]["minimum_added_rendered_chars"] = minimum
    tasks['length_mode'] = 'append_only' if length_only(diagnosis) else 'targeted_repair_with_additions'
    if condition.get('generation_flow')=='separated_v1' and not shortage:
        tasks['length_mode']='targeted_repair_only'
        tasks['completion_conditions'][-1]='Preserve healthy text/relations; length additions run separately.'
    tasks["sentence_errors"] = compact_issues(tasks["sentence_errors"])
    for task in tasks["relations"]:
        task["errors"] = compact_issues(task["errors"])
    return tasks


def relation_repair_schema(source=None,target=None):
    """LLM supplies wording; code supplies mandatory endpoints, IDs and ownership."""
    fragment = {"type":"string","pattern":r"^[^<>\r\n.!?。！？]*$",
                "description":"문장 앞부분이나 연결 구절. 완성 문장과 마침표를 넣지 않는다."}
    nonempty = {"type":"string","pattern":r"^[^<>\r\n.!?。！？]+$",
                "description":"source와 target 사이의 관계 서술. 마침표 없이 이어지는 구절."}
    ending = {"type":"string","pattern":r"^[^<>\r\n.!?。！？]+[.!?。！？]$",
              "description":"바로 앞에 결합되는 엔티티 토큰 뒤 조사·술어와 종결 부호. 결합 후 온전한 한 문장이어야 한다."}
    branches = [
        obj(form=string(["one_sentence"]),before_source=copy.deepcopy(fragment),
            between_entities=copy.deepcopy(nonempty),after_target=copy.deepcopy(ending)),
        obj(form=string(["linked_sentences"]),source_before=copy.deepcopy(fragment),
            source_after=copy.deepcopy(ending),bridge_sentences={**array(copy.deepcopy(ending)),"maxItems":3},
            target_before=copy.deepcopy(fragment),target_after=copy.deepcopy(ending))]
    if source and target:
        plain = r"[^<>\r\n.!?。！？]*"
        src,tgt = re.escape(source),re.escape(target)
        whole = {"type":"string","pattern":f"^(?:{plain}{src}{plain}{tgt}{plain}|{plain}{tgt}{plain}{src}{plain})[.!?。！？]$",
                 "description":"두 endpoint 토큰을 포함하는 자연스러운 완전한 한 문장. 관계·귀속을 실제로 입증한다."}
        def endpoint(token):
            return {"type":"string","pattern":f"^{plain}{re.escape(token)}{plain}[.!?。！？]$"}
        branches = [obj(form=string(["sentence"]),text=whole),
            obj(form=string(["linked_text"]),source_text=endpoint(source),target_text=endpoint(target),bridge_sentences={**array(copy.deepcopy(ending)),"maxItems":3}),*branches]
    return {"anyOf":branches}


def repair_contract(draft, condition, plan, tasks):
    from .stages.stage04_draft import document_contract
    schema = document_contract(condition,plan,patch=True,draft=draft)
    props = schema["properties"]
    scenes = {s["scene_id"]:s for s in plan["scenes"]}
    sections = {s["section_id"]:s for s in condition["section_plan"]}
    originals = {s["sentence_id"]:s for s in draft["segments"]}
    replacements = {}
    for sid in tasks["editable_sentence_ids"]:
        if sid in tasks["reserved_sentence_ids"]:
            continue
        if sid in tasks["protected_sentence_ids"]:
            replacements[sid] = {"type":"null"}
            continue
        segment = copy.deepcopy(props["replacements"]["items"])
        segment["properties"]["sentence_id"]["enum"] = [sid]
        old = originals[sid]
        if old["scene_id"] in scenes:
            owner = scenes[old["scene_id"]]["section_id"]
            segment["properties"]["scene_id"]["enum"] = [old["scene_id"]]
            segment["properties"]["section_id"]["enum"] = [owner]
            segment["properties"]["kind"]["enum"] = [*sections[owner]["allowed_kinds"],"heading"]
        replacements[sid] = segment if sid in tasks["required_replacement_sentence_ids"] else {"anyOf":[{"type":"null"},segment]}
    props["replacements"] = obj(**replacements)
    # Healthy evidence is retained by apply_patch; asking the model to copy it caused regressions.
    props["relation_evidence_updates"] = obj()
    props["relation_repairs"] = obj(**{r["relation_id"]:relation_repair_schema(r["source_placeholder"],r["target_placeholder"]) for r in tasks["relations"] if r["operation"] == "fix"})
    if condition.get('generation_flow')=='separated_v1':
        for unit in props["relation_repairs"]["properties"].values():
            unit["anyOf"] = [branch for branch in unit["anyOf"] if branch["properties"]["form"]["enum"] == ["sentence"]]
    elif condition.get("document_policy") in {"purpose_v2","prose_v1","prose_v2"}:
        for unit in props["relation_repairs"]["properties"].values():
            unit["anyOf"] = [branch for branch in unit["anyOf"] if branch["properties"]["form"]["enum"][0] in {"sentence","linked_text"}]
    props["continuations"] = obj(**{t["scene_id"]:{"type":"string","pattern":r"^[^<>\x00-\x08\x0b\x0c\x0e-\x1f]+$",
        "description":f"기존 {t['section_id']}의 업무 맥락을 이어 쓴 최소 {t['minimum_new_chars']}자 본문. 실제 식별값/엔티티 토큰을 넣지 않는다."}
        for t in tasks["continuation_targets"]})
    schema["required"] = list(props)
    from .renderer import REF_PATTERN
    protected_refs = {rid for s in draft["segments"] if s["sentence_id"] in tasks["protected_sentence_ids"]
                      for rid in REF_PATTERN.findall(s["text"])}
    old_ref_ids = {r["ref_id"] for r in draft["refs"]}
    next_ref = max((int(r[1:]) for r in old_ref_ids if re.fullmatch(r"C[1-9][0-9]*",r)),default=0)+1
    props["refs"]["items"]["properties"]["ref_id"]["enum"] = sorted(old_ref_ids-protected_refs)+[f"C{i}" for i in range(next_ref,next_ref+129)]
    insertion = props["insertions"]["items"]["properties"]
    props["insertions"]["maxItems"] = 16
    insertion["segments"]["maxItems"] = 40
    insertion["after_sentence_id"]["enum"] = ["",*[s["sentence_id"] for s in draft["segments"] if s["scene_id"] in tasks["insertion_scene_ids"]]]
    if tasks["insertion_scene_ids"]:
        branches = []
        for scene_id in tasks["insertion_scene_ids"]:
            segment = copy.deepcopy(insertion["segments"]["items"])
            owner = scenes[scene_id]["section_id"]
            segment["properties"]["scene_id"]["enum"] = [scene_id]
            segment["properties"]["section_id"]["enum"] = [owner]
            segment["properties"]["kind"]["enum"] = [*sections[owner]["allowed_kinds"],"heading"]
            branches.append(segment)
        insertion["segments"]["items"] = {"anyOf":branches}
    else:
        props["insertions"]["maxItems"] = 0
    if condition.get('generation_flow')=='separated_v1' and not tasks["editable_sentence_ids"] and not tasks["sentence_errors"] and not tasks["continuation_targets"]:
        repaired_entities={r[key][1:-1].split(':',1)[1] for r in tasks["relations"] if r["operation"]=='fix'
                           for key in ("source_placeholder","target_placeholder")}
        if {e["entity_id"] for e in tasks["missing_entities"]} <= repaired_entities:
            props["insertions"]["maxItems"] = 0
    if tasks.get('length_mode') == 'append_only':
        # Only new context can be emitted. Keep original words, refs and all
        # relation evidence immutable; continuations are decoded into insertions.
        props['replacements'] = obj()
        props['relation_repairs'] = obj()
        props['relation_evidence_updates'] = obj()
        props['refs']['maxItems'] = 0
        props['insertions']['maxItems'] = 0
    return schema


def decode_patch(response, schema, draft=None, condition=None, plan=None, tasks=None):
    validate(response,schema)
    patch = copy.deepcopy(response)
    patch["replacements"] = [s for s in response["replacements"].values() if s is not None]
    patch["relation_evidence_updates"] = [{"relation_id":rid,"evidence_groups":groups}
                                         for rid,groups in response["relation_evidence_updates"].items()]
    repairs = patch.pop("relation_repairs",{})
    continuations = patch.pop("continuations",{})
    if repairs or continuations:
        if draft is None or condition is None or plan is None or tasks is None:
            raise ValueError("Bound repair decoding requires draft, condition, plan and repair tasks")
        task_map = {r["relation_id"]:r for r in tasks["relations"]}
        sections = {s["section_id"]:s for s in condition["section_plan"]}
        originals = {s["sentence_id"]:s for s in draft["segments"]}
        used = set(originals) | {s["sentence_id"] for ins in patch["insertions"] for s in ins["segments"]}
        serial = max((int(sid[1:]) for sid in used),default=0)+1
        for rid,unit in repairs.items():
            task = task_map[rid]
            if unit["form"] == "sentence":
                texts = [unit["text"]]
            elif unit["form"] == "linked_text":
                texts = [unit["source_text"],*unit["bridge_sentences"],unit["target_text"]]
            elif unit["form"] == "one_sentence":
                texts = [unit["before_source"]+task["source_placeholder"]+unit["between_entities"]+task["target_placeholder"]+unit["after_target"]]
            else:
                texts = [unit["source_before"]+task["source_placeholder"]+unit["source_after"],
                         *unit["bridge_sentences"],unit["target_before"]+task["target_placeholder"]+unit["target_after"]]
            replacement = task["replacement_sentence_id"]
            allowed = sections[task["section_id"]]["allowed_kinds"]
            kind = originals[replacement]["kind"] if replacement and originals[replacement]["kind"] in allowed else next((k for k in ("prose","answer","item","field") if k in allowed),allowed[0])
            segments = []
            for index,text in enumerate(texts):
                sid = replacement if index == 0 and replacement else f"S{serial}"
                if not (index == 0 and replacement):
                    serial += 1
                segments.append({"sentence_id":sid,"section_id":task["section_id"],"scene_id":task["scene_id"],"kind":kind,"text":text})
            if replacement:
                patch["replacements"].append(segments[0])
                added = segments[1:]
            else:
                added = segments
            if added:
                patch["insertions"].append({"after_sentence_id":task["insertion_after_sentence_id"],"segments":added})
            group = [segments[0]["sentence_id"]] if len(segments) == 1 else [segments[0]["sentence_id"],segments[-1]["sentence_id"]]
            patch["relation_evidence_updates"].append({"relation_id":rid,"evidence_groups":[group]})
        for target in tasks["continuation_targets"]:
            allowed = sections[target["section_id"]]["allowed_kinds"]
            kind = next((k for k in ("prose","answer","item","field") if k in allowed),allowed[0])
            segment = {"sentence_id":f"S{serial}","section_id":target["section_id"],"scene_id":target["scene_id"],
                       "kind":kind,"text":continuations[target["scene_id"]]}
            serial += 1
            patch["insertions"].append({"after_sentence_id":target["after_sentence_id"],"segments":[segment]})
    return patch


def evaluate_repair(before, after, plan, before_diagnosis, after_diagnosis, tasks):
    from .stages.stage05_assemble import evidence_issues
    missing = [e["entity_id"] for e in tasks["missing_entities"]]
    remaining = sorted({e["entity_id"] for e in plan["entities"]}-actual_entities(after,plan))
    refs = {r["ref_id"]:r for r in after["refs"]}
    evidence = {r["relation_id"]:r["evidence_groups"] for r in after["relation_evidence"]}
    relations = {r["relation_id"]:r for r in plan["relations"]}
    invalid = [t["relation_id"] for t in tasks["relations"] if evidence_issues(evidence.get(t["relation_id"],[]),after["segments"],
        (relations[t["relation_id"]]["source"],relations[t["relation_id"]]["target"]),refs)]
    old = {s["sentence_id"]:s for s in before["segments"]}
    changed = [s["sentence_id"] for s in after["segments"] if old.get(s["sentence_id"]) != s]
    changed_scenes = {s["scene_id"] for s in after["segments"] if s["sentence_id"] in changed}
    refs_changed = before["refs"] != after["refs"]
    guards = []
    for i in before_diagnosis["issues"]:
        if i["code"] not in SEMANTIC_CODES:
            continue
        rid = i.get("relation_id")
        if not ((relations[rid]["scene_id"] in changed_scenes if rid in relations else bool(changed)) or refs_changed):
            guards.append(copy.deepcopy(i))
            guards.append(Issue("REPAIR_BODY_UNCHANGED","Semantic failure requires a text/reference correction, not only evidence IDs.","REWRITE_SCENE",relation_id=rid or "").json())
    guards = list({(i["code"],i.get("relation_id",""),i.get("sentence_id","")):i for i in guards}.values())
    counts = lambda d:dict(collections.Counter(i["code"] for i in d["issues"]))
    issue_keys = lambda d:{(i["code"],*(i.get(k,"") for k in ("entity_id","relation_id","sentence_id","section_id"))) for i in d["issues"]}
    before_keys,after_keys = issue_keys(before_diagnosis),issue_keys(after_diagnosis)
    satisfied = not remaining and not invalid and not guards
    report = {"requested_missing_entities":missing,"remaining_missing_entities":remaining,
        "new_missing_entities":sorted(set(remaining)-set(missing)),
        "requested_relation_ids":[r["relation_id"] for r in tasks["relations"]],"remaining_invalid_relation_ids":invalid,
        "structural_targets_satisfied":satisfied,"all_code_checks_passed":not after_diagnosis["issues"] and not guards,
        "changed_sentence_ids":changed,"refs_changed":refs_changed,"before_issue_counts":counts(before_diagnosis),"after_issue_counts":counts(after_diagnosis),
        "resolved_issue_count":len(before_keys-after_keys),"new_issue_count":len(after_keys-before_keys),
        "no_effective_progress":not bool(before_keys-after_keys) and not bool(set(missing)-set(remaining)),
        "length_only_progress":counts(before_diagnosis).get("LENGTH_SHORTAGE",0)>counts(after_diagnosis).get("LENGTH_SHORTAGE",0) and not satisfied,
        "before_rendered_chars":before_diagnosis.get("metrics",{}).get("rendered_chars"),"after_rendered_chars":after_diagnosis.get("metrics",{}).get("rendered_chars"),
        "unresolved_semantic_issues":guards,"semantic_verification":"independent_review_required"}
    return report,guards
