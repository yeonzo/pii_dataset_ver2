"""Deterministic mock provider for integration checks; never a quality benchmark.

Simulated reviews deliberately use fixture metadata. Live review payloads do not.
Outputs are isolated by run ID and explicitly marked mode=offline in audits/stats.
"""
from __future__ import annotations

import collections
import math
import random

from .common import StageFailure, digest, fail, now, read_json
from .client import build_body
from .formats import allowed_triples
from .renderer import PLACEHOLDER
from .schemas import validate
from .planning_seed import seed_plan


class OfflineClient:
    def __init__(self, config, store, scenario="normal"):
        self.config, self.store, self.scenario = config, store, scenario

    def request(self, candidate, stage, task, system, payload, schema):
        count = self.store.db.execute("SELECT COUNT(*) FROM api_calls WHERE candidate_id=?", (candidate,)).fetchone()[0]
        total = self.store.db.execute("SELECT COUNT(*) FROM api_calls").fetchone()[0]
        if count >= self.config["max_provider_requests_per_candidate"]:
            fail("CANDIDATE_CALL_LIMIT", "Offline simulated request cap reached", "STOP_CANDIDATE")
        if total >= self.config["run_request_budget"]:
            fail("RUN_REQUEST_BUDGET", "Offline simulated request budget reached", "STOP_RUN", True)
        model = self.config["review_model" if task == "review" else "generation_model"]
        call = self.store.execute("INSERT INTO api_calls(candidate_id,stage,task,model,key_slot,status,started_at,finished_at) VALUES(?,?,?,?,?,'offline_simulated',?,?)",
                                  (candidate, stage, task, model, "OFFLINE", now(), now())).lastrowid
        self.store.save_artifact(candidate, f"api/request_{call:05d}.json",
                                 {"mode":"offline", "task":task, "body":build_body(self.config,task,system,payload,schema)}, private=True)
        if task == "plan":
            if "slot_groups" in schema["properties"]:
                result = {"slot_groups":payload["baseline_slot_groups"],"slot_constraints":[c for c in payload["existing_plan"]["slot_constraints"]
                    if c["kind"] not in ("same_persona","same_organization")]}
            else:
                seed = payload.get("seed_plan") or {'relations':[dict(r,context_reason='',scene_id='') for r in payload['relations']],
                                                    'scenes':[dict(s,outline='') for s in payload['scenes']]}
                result = {"relation_contexts":{r["relation_id"]:{"context_reason":r["context_reason"] or "모의 문서에서 해당 역할과 정보 귀속을 확인했다.","scene_id":r["scene_id"]} for r in seed["relations"]},
                    "scene_notes":{s["scene_id"]:{"purpose":s["purpose"],"outline":s["outline"] or "모의 처리의 사실과 결과를 기록했다."} for s in seed["scenes"]}}
                for index,relation in enumerate(result["relation_contexts"].values()):
                    if not relation["scene_id"]:
                        relation["scene_id"] = seed["scenes"][index % len(seed["scenes"])]["scene_id"]
                for sid,note in result["scene_notes"].items():
                    if "facts" in schema["properties"]["scene_notes"]["properties"][sid]["properties"]:
                        note["facts"] = [note.pop("outline"),"모의 점검 결과를 확인했다."]
                if 'story' in schema['properties']:
                    result['story']={'situation':'모의 접수 기록을 점검했다.','action':'모의 오류 항목을 확인했다.','outcome':'모의 결과를 기록했다.'}
        elif task == "draft":
            # Fixture randomness needs an audit ID; it is not part of model input.
            if 'sections' in schema['properties']:
                root=self.store.run_dir/'candidates'/candidate
                condition,plan=read_json(root/'condition.json'),read_json(root/'plan.json')
                mock=self.draft(condition,plan,self.scenario!='short_then_repair')
                refs={r['ref_id']:r['entity_id'] for r in mock['refs']}
                types={e['entity_id']:e['entity_type'] for e in plan['entities']}
                import re
                result={'sections':{s['section_id']:[] for s in condition['section_plan']}}
                for segment in mock['segments']:
                    text=re.sub(r'<REF:(C\d+)>',lambda m:f"<{types[refs[m[1]]]}:{refs[m[1]]}>",segment['text'])
                    result['sections'][segment['section_id']].append(text)
            else:
                result = self.draft({**payload["condition"], "candidate_id":candidate}, payload["plan"], self.scenario != "short_then_repair")
        elif task == "repair":
            result = self.repair({**payload, "condition":{**payload["condition"], "candidate_id":candidate}})
            # Wire schema uses unique object keys; downstream still receives ordinary PATCH arrays.
            result["replacements"] = {sid:next((s for s in result["replacements"] if s["sentence_id"] == sid),None)
                                      for sid in schema["properties"]["replacements"]["properties"]}
            prior = {e["relation_id"]:e["evidence_groups"] for e in payload["draft"]["relation_evidence"]}
            updates = {e["relation_id"]:e["evidence_groups"] for e in result["relation_evidence_updates"]}
            result["relation_evidence_updates"] = {rid:updates.get(rid,prior.get(rid,[]))
                for rid in schema["properties"]["relation_evidence_updates"]["properties"]}
            # Fixture text is deliberately simple, never used as a live quality claim.
            result["relation_repairs"] = {rid:{"form":"one_sentence","before_source":"",
                "between_entities":"의 확인 항목 "+next(r["relation"] for r in payload["repair_tasks"]["relations"] if r["relation_id"] == rid)+"의 대상은 ",
                "after_target":"이다."} for rid in schema["properties"]["relation_repairs"]["properties"]}
            for rid,unit in schema["properties"]["relation_repairs"]["properties"].items():
                if len(unit["anyOf"]) == 2 and unit["anyOf"][0]["properties"]["form"]["enum"] == ["sentence"]:
                    task = next(r for r in payload["repair_tasks"]["relations"] if r["relation_id"] == rid)
                    result["relation_repairs"][rid] = {"form":"sentence","text":task["source_placeholder"]+"의 확인 대상은 "+task["target_placeholder"]+"이다."}
            result["continuations"] = {}
            rng = random.Random(42)
            for target in payload["repair_tasks"]["continuation_targets"]:
                text = ""
                while len(text) < target["minimum_new_chars"]:
                    text += self.filler(rng)+" "
                result["continuations"][target["scene_id"]] = text
            if result["continuations"]:
                result["insertions"] = []
        elif task == "review":
            result = self.review(candidate, payload)
            if 'evidence_quotes' not in schema['properties']['relation_checks']['items']['properties'] and 'relation_checks' in result:
                for item in [*result['relation_checks'],*result['reference_checks'],*result['missing_relations'],*result['person_checks']['observed_persons']]:
                    item.pop('evidence_quotes',None)
        else:
            fail("OFFLINE_TASK", task, "CODE_FIX", True)
        try:
            validate(result, schema)
        except StageFailure as exc:
            if task == "review" and isinstance(result, dict):
                exc.review_response = result
            raise
        self.store.save_artifact(candidate, f"api/offline_{call:05d}.json", {"mode": "offline", "task": task, "output": result})
        return result

    def plan(self, condition):
        return seed_plan(condition, allowed_triples(condition["domain"]))

    @staticmethod
    def filler(rng):
        # Unique mock notes keep independent fixtures from being exact-content duplicates.
        note = "".join(rng.choice("가나다라마바사아자차카타파하거너더러머버서어저처커터퍼허") for _ in range(36))
        return f"오프라인 점검 메모 {note}의 처리 순서를 확인하고, 접수 내용과 후속 안내가 같은 업무 흐름에 포함되는지 검토했다."

    def draft(self, condition, plan, full_length=True):
        types = {e["entity_id"]: e["entity_type"] for e in plan["entities"]}
        rng = random.Random(int(digest([condition["candidate_id"], "offline_draft"])[:16], 16))
        refs, evidence = [], []
        scene_segments = collections.defaultdict(list)
        # Assign permanent S IDs before ordering sections, exactly as the live contract allows.
        next_sentence = 1
        def add(scene, text, kind="prose"):
            nonlocal next_sentence
            sid = f"S{next_sentence}"
            next_sentence += 1
            section = next(s["section_id"] for s in plan["scenes"] if s["scene_id"] == scene)
            scene_segments[scene].append({"sentence_id": sid, "section_id": section, "scene_id": scene, "kind": kind, "text": text})
            return sid
        def token(eid):
            return f"<{types[eid]}:{eid}>"
        for scene in plan["scenes"]:
            section = next(s for s in condition["section_plan"] if s["section_id"] == scene["section_id"])
            add(scene["scene_id"], section["title"], "heading")
        for index, relation in enumerate(plan["relations"]):
            scene = relation["scene_id"]
            source, target = token(relation["source"]), token(relation["target"])
            # Test fixture coverage only: production never assigns modes to relations.
            mode = ("single", "adjacent", "nonadjacent")[index % 3]
            if mode == "single":
                group = [add(scene, source + "{josa:의} 확인 항목 " + relation["relation"] + "의 대상은 " + target + "이다.")]
            else:
                rid = f"C{len(refs)+1}"
                refs.append({"ref_id": rid, "entity_id": relation["source"], "surface": "해당 접수 주체", "kind": "role"})
                first = add(scene, "이번 확인의 접수 주체는 " + source + "이다.")
                if mode == "nonadjacent":
                    add(scene, self.filler(rng))
                last = add(scene, f"<REF:{rid}>" + "{josa:의} 확인 항목 " + relation["relation"] + "의 대상은 " + target + "이다.")
                group = [first, last]
            evidence.append({"relation_id": relation["relation_id"], "evidence_groups": [group]})
        for scene in plan["scenes"]:
            section = next(s for s in condition["section_plan"] if s["section_id"] == scene["section_id"])
            if condition["layout_variant"] == "question_answer" and scene["section_id"] == "questions":
                add(scene["scene_id"], "접수 이후 어떤 사항을 확인했습니까?", "question")
                add(scene["scene_id"], "처리 순서와 다음 안내 일정을 확인했습니다.", "answer")
            if full_length:
                while sum(len(s["text"]) for s in scene_segments[scene["scene_id"]]) < section["target_chars"] + 120:
                    add(scene["scene_id"], self.filler(rng))
        minimum = max(12,math.ceil(condition["length_target"]/80))
        while sum(len(items) for items in scene_segments.values()) < minimum:
            add(plan["scenes"][-1]["scene_id"], self.filler(rng) if full_length else "접수 절차를 확인했다.")
        segments = [seg for scene in sorted(plan["scenes"], key=lambda s:s["order"]) for seg in scene_segments[scene["scene_id"]]]
        return {"draft_version": 1, "segments": segments, "refs": refs, "relation_evidence": evidence}

    def repair(self, payload):
        draft, condition = payload["draft"], payload["condition"]
        rng = random.Random(int(digest([condition["candidate_id"], "offline_repair"])[:16], 16))
        next_id = int(payload["new_sentence_id_start"][1:])
        insertions = []
        if self.scenario != "review_privacy_failure":
            for section in condition["section_plan"]:
                existing = [s for s in draft["segments"] if s["section_id"] == section["section_id"]]
                if not existing:
                    continue
                needed = max(0, section["target_chars"] + 150 - sum(len(s["text"]) for s in existing))
                additions = []
                while needed > 0:
                    text = self.filler(rng)
                    additions.append({**existing[-1], "sentence_id": f"S{next_id}", "kind": "prose", "text": text})
                    next_id += 1
                    needed -= len(text)
                if additions:
                    insertions.append({"after_sentence_id": existing[-1]["sentence_id"], "segments": additions})
        return {"base_draft_version": draft["draft_version"], "insertions": insertions,
                "replacements": [], "refs": [], "relation_evidence_updates": []}

    def review(self, candidate, payload):
        root = self.store.run_dir / "candidates" / candidate
        plan = read_json(root / "plan.json")
        draft = read_json(root / "assembled.json")["draft"]
        sentences = {s["sentence_id"]: s for s in payload["sentences"]}
        evidence = {e["relation_id"]: e["evidence_groups"] for e in draft["relation_evidence"]}
        def quotes(groups):
            return [{"sentence_id": sid, "quote": sentences[sid]["sentence"]}
                    for sid in sorted({sid for group in groups for sid in group})]
        checks = [{"relation_id": r["relation_id"], "extractable": True, "observed_privacy": r["target_privacy"],
                   "direction_supported": True, "evidence_groups": evidence[r["relation_id"]],
                   "evidence_quotes": quotes(evidence[r["relation_id"]]), "coreference_unambiguous": True,
                   "single_sentence_sufficient": any(len(g)==1 for g in evidence[r["relation_id"]]), "reason": "오프라인 fixture 모의 판정"}
                  for r in plan["relations"]]
        if self.scenario == "review_privacy_failure":
            checks[0]["observed_privacy"] = "NON_PII" if checks[0]["observed_privacy"] == "PII" else "PII"
        if self.scenario == "review_ambiguous":
            checks[0]["observed_privacy"] = "AMBIGUOUS"
            checks[0]["reason"] = "오프라인 fixture: 전체 맥락에서도 개인/공용 귀속을 확정할 수 없음"
        ref_checks = []
        for ref in draft["refs"]:
            appearances = [s["sentence_id"] for s in draft["segments"] if f"<REF:{ref['ref_id']}>" in s["text"]]
            eid = ref["entity_id"]
            mentions = [m["sentence_id"] for e in payload["entities"] if e["entity_id"] == eid for m in e["mentions"]]
            target_sid = max((sid for sid in mentions if sentences[sid]["sent_idx"] <= sentences[appearances[0]]["sent_idx"]),
                             key=lambda sid:sentences[sid]["sent_idx"], default=mentions[0])
            groups = [list(dict.fromkeys([target_sid, *appearances]))]
            ref_checks.append({"ref_id": ref["ref_id"], "observed_entity_id": eid, "unambiguous": True,
                               "evidence_groups": groups, "evidence_quotes": quotes(groups), "reason": "오프라인 fixture 지시어 연결"})
        result = {"relation_checks": checks, "reference_checks": ref_checks, "missing_relations": [],
                "unregistered_entities": [], "contradictions": [], "text_issues":[],
                "person_checks":{"actual_person_count":sum(p['context_kind']=='actual_party' for p in plan['persons']),
                    "observed_persons":[{"name_entity_id":p["name_entity_id"],"role":p["role"],"context_kind":p["context_kind"],
                        "evidence_groups":[[next(m["sentence_id"] for e in payload["entities"] if e["entity_id"] == p["name_entity_id"] for m in e["mentions"])]],
                        "evidence_quotes":quotes([[next(m["sentence_id"] for e in payload["entities"] if e["entity_id"] == p["name_entity_id"] for m in e["mentions"])]])}
                        for p in plan["persons"]],"reason":"모의 인물 관찰이며 의미 품질 측정이 아님"},
                "format_adherence": {"document_format_supported": True, "layout_variant_supported": True,
                                     "viewpoint_supported": True, "section_roles_supported": True, "reason": "오프라인 모의 형식 판정"},
                "quality": {"overall": "상", "scores": {"consistency": "상", "fluency": "상", "suitability": "상"},
                            "reason": "모의 점검용 등급이며 실제 문서 품질 측정이 아님"}}
        if self.scenario == "review_schema_then_retry" and not payload.get("response_contract_feedback"):
            return {"quality": result["quality"]}
        return result
