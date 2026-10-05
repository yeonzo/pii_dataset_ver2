"""Two sequential, scene-based draft calls under the original whole-document contract."""
from __future__ import annotations

from copy import deepcopy

from relation_pipeline.client import Client
from relation_pipeline.common import StageFailure, fail
from relation_pipeline.schemas import validate
from relation_pipeline.stages import stage04_draft as s4


def partition(condition, plan):
    """Keep sections/scenes in order; prefer a cut with both privacy classes in each part."""
    sections = condition["section_plan"]
    if len(sections) < 2:
        fail("EXPERIMENT_UNSPLITTABLE", "At least two sections are required", "STOP_CANDIDATE")
    candidates = []
    for cut in range(1, len(sections)):
        left = {s["section_id"] for s in sections[:cut]}
        scene_left = {s["scene_id"] for s in plan["scenes"] if s["section_id"] in left}
        groups = [[r for r in plan["relations"] if (r["scene_id"] in scene_left) == flag]
                  for flag in (True, False)]
        if any(not group for group in groups):
            continue
        mixed = all({r["target_privacy"] for r in group} == {"PII", "NON_PII"} for group in groups)
        size = sum(s["target_chars"] for s in sections[:cut])
        candidates.append((not mixed, abs(size-condition["length_target"]/2), cut))
    if not candidates:
        fail("EXPERIMENT_UNSPLITTABLE", "Relations cannot be partitioned by section", "STOP_CANDIDATE")
    cut = min(candidates)[2]
    full_contract = s4.document_contract(condition, plan)
    bounds = full_contract["properties"]["segments"]
    result = []
    for index, section_group in enumerate((sections[:cut], sections[cut:])):
        part_condition = deepcopy(condition)
        part_condition["section_plan"] = deepcopy(section_group)
        part_condition["length_target"] = sum(s["target_chars"] for s in section_group)
        weight = part_condition["length_target"]/condition["length_target"]
        part_condition["min_chars"] = round(condition["min_chars"]*weight)
        section_ids = {s["section_id"] for s in section_group}
        scenes = [s for s in plan["scenes"] if s["section_id"] in section_ids]
        scene_ids = {s["scene_id"] for s in scenes}
        relations = [r for r in plan["relations"] if r["scene_id"] in scene_ids]
        entity_ids = {r[k] for r in relations for k in ("source", "target")}
        part_plan = {"entities":deepcopy([e for e in plan["entities"] if e["entity_id"] in entity_ids]),
                     "relations":deepcopy(relations), "scenes":deepcopy(scenes),
                     "slot_constraints":deepcopy([c for c in plan["slot_constraints"]
                                                   if set(c["entity_ids"]) <= entity_ids])}
        schema = s4.document_contract(part_condition, part_plan)
        # Natural remention across batches must remain possible, just as in the full draft.
        # Only scene/section/relation ownership is partitioned; planned entity identity is global.
        schema["properties"]["segments"]["items"]["properties"]["text"] = deepcopy(
            full_contract["properties"]["segments"]["items"]["properties"]["text"])
        schema["properties"]["refs"]["items"]["properties"]["entity_id"] = deepcopy(
            full_contract["properties"]["refs"]["items"]["properties"]["entity_id"])
        segment_bounds = schema["properties"]["segments"]
        for key in ("minItems", "maxItems"):
            first = round(bounds[key]*result[0]["weight"]) if result else round(bounds[key]*weight)
            segment_bounds[key] = first if index == 0 else bounds[key]-first
        schema["properties"]["segments"]["items"]["properties"]["sentence_id"]["pattern"] = (
            r"^S[1-9][0-9]{0,2}$" if index == 0 else r"^S1[0-9]{3}$")
        schema["properties"]["refs"]["items"]["properties"]["ref_id"]["pattern"] = (
            r"^C[1-9][0-9]{0,2}$" if index == 0 else r"^C1[0-9]{3}$")
        result.append({"condition":part_condition, "plan":part_plan, "schema":schema, "weight":weight,
                       "privacy_counts":{p:sum(r["target_privacy"] == p for r in relations) for p in ("PII","NON_PII")}})
    return result


def merge(parts, full_schema):
    merged = {"draft_version":1, "segments":[], "refs":[], "relation_evidence":[]}
    for part in parts:
        for key in ("segments", "refs", "relation_evidence"):
            merged[key].extend(deepcopy(part[key]))
    for key, field in (("segments","sentence_id"),("refs","ref_id"),("relation_evidence","relation_id")):
        ids = [item[field] for item in merged[key]]
        if len(ids) != len(set(ids)):
            fail("EXPERIMENT_MERGE_COLLISION", key, "STOP_CANDIDATE")
    validate(merged, full_schema)
    return merged


class SplitClient:
    """Intercept only the initial draft; planning, repair and review use unchanged prompts."""
    def __init__(self, client):
        self.client = client
        cfg = deepcopy(client.config)
        cfg["max_output_tokens"]["draft"] //= 2
        self.batch_client = Client(cfg, client.store)
        self.started = set()

    def request(self, candidate, stage, task, system, payload, schema):
        if task != "draft" or candidate in self.started:
            return self.client.request(candidate, stage, task, system, payload, schema)
        self.started.add(candidate)
        condition, plan = payload["condition"], payload["plan"]
        assignments = partition(condition, plan)
        outputs = []
        for index, part in enumerate(assignments):
            batch_input = s4.draft_input(part["condition"], part["plan"], payload.get("feedback"))
            batch_input["batch"] = {"number":index+1,"total":2,
                "sentence_id_start":"S1" if index == 0 else "S1000",
                "ref_id_start":"C1" if index == 0 else "C1000"}
            batch_input["whole_document_context"] = {
                "topic":condition["topic"], "length_target":condition["length_target"],
                "scenes":deepcopy(plan["scenes"]), "entities":deepcopy(plan["entities"]),
                "relations":deepcopy(plan["relations"])}
            batch_input["previous_segments"] = deepcopy(outputs[0]["segments"]) if outputs else []
            batch_input["previous_refs"] = deepcopy(outputs[0]["refs"]) if outputs else []
            batch_system = system.replace("계획에 맞는 완성된 한국어 문서 전체를 한 번에 작성한다.",
                "같은 문서의 지정된 부분을 작성한다. 두 부분을 순서대로 합쳐 최종 문서를 구성한다.")
            batch_system += ("\n[부분 생성 범위]\n"
                "plan과 condition.section_plan에 배정된 장면·관계·section만 출력한다. "
                "whole_document_context와 previous_segments는 동일 사건의 맥락이다. 앞부분을 복사하지 않는다. "
                "전체 계획의 기존 엔티티는 필요하면 재언급할 수 있다. 해당 부분에 배정된 엔티티와 관계는 반드시 작성한다. "
                "배정된 PII와 NON_PII 관계를 같은 업무 맥락에서 함께 작성한다. "
                "batch.sentence_id_start/ref_id_start부터 번호를 매기고 앞부분 ID를 재정의하지 않는다. "
                "근거가 앞부분에 있으면 그 문장 ID를 evidence_groups에 사용할 수 있다.\n")
            output = self.batch_client.request(candidate, stage, task, batch_system, batch_input, part["schema"])
            self.client.store.save_artifact(candidate, f"experiment/batch_{index+1}.json", output)
            self.client.store.save_artifact(candidate, f"experiment/assignment_{index+1}.json", {
                "sections":[s["section_id"] for s in part["condition"]["section_plan"]],
                "relation_ids":[r["relation_id"] for r in part["plan"]["relations"]],
                "privacy_counts":part["privacy_counts"],"length_target":part["condition"]["length_target"],
                "segment_min":part["schema"]["properties"]["segments"]["minItems"],
                "segment_max":part["schema"]["properties"]["segments"]["maxItems"]})
            outputs.append(output)
        return merge(outputs, schema)
