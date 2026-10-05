"""Regression checks for graph coverage, mention spans and repair boundaries."""
from __future__ import annotations

import copy
import unittest

from relation_pipeline.common import StageFailure
from relation_pipeline.distribution import measure
from relation_pipeline.evidence import observed_expression
from relation_pipeline.renderer import normalize, render
from relation_pipeline.stages.stage02_plan import check_plan, plan_fingerprint, planning_contract, privacy_groups
from relation_pipeline.schemas import PLAN, validate
from relation_pipeline.planning_seed import relation_slots
from relation_pipeline.persons import seed_person_links
from relation_pipeline.stages.stage04_draft import document_contract
from relation_pipeline.stages.stage05_assemble import apply_patch, diagnose, evidence_issues
from relation_pipeline.stages.stage07_review import check_review, review_input
from relation_pipeline.stages.stage08_accept import annotate


def fixture():
    types = ["NAME", "MOBILE_PHONE", "WORKPLACE", "EMAIL", "ADDRESS"]
    entities = [{"entity_id": f"E{i}", "entity_type": typ,
                 "context_role": "applicant" if typ == "NAME" else "public_office" if i >= 3 else "personal_contact",
                 "slot_group": ""} for i, typ in enumerate(types, 1)]
    edges = [("E1", "E2", "CONTACT_ASSOCIATION", "PII"),
             ("E3", "E4", "CONTACT_ASSOCIATION", "NON_PII"),
             ("E3", "E5", "LOCATION_ASSOCIATION", "NON_PII")]
    plan = {"plan_version": 1, "entities": entities,
            "relations": [{"relation_id": f"R{i}", "source": source, "target": target,
                           "relation": relation, "target_privacy": privacy,
                           "context_reason": "개인 귀속" if privacy == "PII" else "기관의 공용 정보",
                           "scene_id": "SC1"}
                          for i, (source, target, relation, privacy) in enumerate(edges, 1)],
            "scenes": [{"scene_id": "SC1", "section_id": "main", "order": 1,
                        "purpose": "상담 접수", "relation_ids": ["R1", "R2", "R3"], "outline": "연락과 위치 안내"}],
            "slot_constraints": []}
    condition = {"candidate_id": "fixture", "domain": "support", "allowed_personal_types": types,
                 "allowed_public_types": types, "relation_count": 3,
                 "pii_relation_target": 1, "non_pii_relation_target": 2,
                 "non_pii_only_min": 2, "mention_policy": "natural", "expression_policy": "observe_only",
                 "section_plan": [{"section_id": "main", "title": "접수 내용", "allowed_kinds": ["prose"]}],
                 "subtype": "support_ticket", "subtype_label": "고객지원 티켓", "document_format": "consultation_record",
                 "layout_variant": "narrative", "layout_variant_label": "자유 서술형 업무 기록", "narrative_viewpoint": "staff_record",
                 }
    surfaces = ["가온", "010-0000-0000", "누리센터", "office@example.invalid", "서울시 가상구 예시로 1"]
    values = {f"E{i}": {"value": value, "canonical_form": value} for i, value in enumerate(surfaces, 1)}
    texts = ["<NAME:E1>{josa:은/는} 연락처로 <MOBILE_PHONE:E2>{josa:을/를} 기재했다.",
             "<WORKPLACE:E3>{josa:의} 공용 메일은 <EMAIL:E4>이다.",
             "<WORKPLACE:E3>{josa:의} 공용 사무실은 <ADDRESS:E5>에 있다.",
             "<NAME:E1>{josa:은/는} 안내를 확인했고, <NAME:E1>{josa:의} 접수는 완료됐다.",
             "<REF:C1>{josa:은/는} 다음 절차를 확인했다."]
    draft = {"draft_version": 1,
             "segments": [{"sentence_id": f"S{i}", "section_id": "main", "scene_id": "SC1",
                           "kind": "prose", "text": text} for i, text in enumerate(texts, 1)],
             "refs": [{"ref_id": "C1", "entity_id": "E1", "surface": "신청인", "kind": "role"}],
             "relation_evidence": [{"relation_id": f"R{i}", "evidence_groups": [[f"S{i}"]]}
                                   for i in range(1, 4)]}
    plan["persons"], plan["person_entity_links"] = seed_person_links(plan, condition)
    return plan, condition, values, draft


def good_review(filled, plan):
    sentences = {s["sentence_id"]: s for s in filled["sentences"]}
    return {"relation_checks": [
        {"relation_id": f"R{i}", "extractable": True, "observed_privacy": r["target_privacy"],
         "direction_supported": True, "evidence_groups": [[f"S{i}"]],
         "evidence_quotes": [{"sentence_id": f"S{i}", "quote": sentences[f"S{i}"]["sentence"]}],
         "coreference_unambiguous": True, "single_sentence_sufficient": True, "reason": "본문에서 확인됨"}
        for i, r in enumerate(plan["relations"], 1)],
        "reference_checks": [{"ref_id": "C1", "observed_entity_id": "E1", "unambiguous": True,
                              "evidence_groups": [["S4", "S5"]],
                              "evidence_quotes": [{"sentence_id": sid, "quote": sentences[sid]["sentence"]}
                                                  for sid in ("S4", "S5")], "reason": "같은 신청인"}],
        "missing_relations": [], "unregistered_entities": [], "contradictions": [], "text_issues":[],
        "person_checks": {"actual_person_count":len(plan["persons"]), "observed_persons":[
            {"name_entity_id":p["name_entity_id"], "role":p["role"], "context_kind":p["context_kind"],
             "evidence_groups":[["S1"]], "evidence_quotes":[{"sentence_id":"S1", "quote":sentences["S1"]["sentence"]}]}
            for p in plan["persons"]], "reason":"모의 인물 관찰"},
        "format_adherence": {"document_format_supported": True, "layout_variant_supported": True,
                             "viewpoint_supported": True, "section_roles_supported": True, "reason": "형식 충족"},
        "quality": {"overall": "상", "scores": {"consistency": "상", "fluency": "중", "suitability": "상"}, "reason": "통과"}}


class ContinuationTests(unittest.TestCase):
    def test_document_contract_rejects_wrong_type_id_tag_without_schema_aliasing(self):
        plan, condition, _, draft = fixture()
        condition["length_target"] = 1600
        schema = document_contract(condition, plan)
        self.assertEqual(schema["properties"]["segments"]["minItems"], 20)
        segment_schema = schema["properties"]["segments"]["items"]
        validate(draft["segments"][0], segment_schema)
        malformed = {**draft["segments"][0], "text": "<EMAIL:E1>을 확인했다."}
        with self.assertRaises(StageFailure):
            validate(malformed, segment_schema)
        self.assertNotIn("pattern", segment_schema["properties"]["kind"])

    def test_document_contract_accepts_single_and_multi_evidence_without_quotas(self):
        plan, condition, _, draft = fixture()
        condition["length_target"] = 800
        schema = document_contract(condition, plan)
        reference_schema = schema["properties"]["refs"]["items"]
        validate(draft["refs"][0], reference_schema)
        with self.assertRaises(StageFailure):
            validate({**draft["refs"][0], "surface":"<NAME:E1>"}, reference_schema)
        evidence_schema = schema["properties"]["relation_evidence"]["items"]
        validate({"relation_id":"R1", "evidence_groups":[["S1"]]}, evidence_schema)
        validate({"relation_id":"R2", "evidence_groups":[["S2","S3"]]}, evidence_schema)
        validate({"relation_id":"R1", "evidence_groups":[["S1","S2"]]}, evidence_schema)
        validate({"relation_id":"R2", "evidence_groups":[["S2"]]}, evidence_schema)
        for invalid in ({"relation_id":"R1", "evidence_groups":[[]]},
                        {"relation_id":"R2", "evidence_groups":[["UNKNOWN"]]}):
            with self.assertRaises(StageFailure):
                validate(invalid, evidence_schema)

    def test_section_and_single_evidence_normalization_keep_independent_gate(self):
        plan, condition, values, draft = fixture()
        condition["min_chars"] = 0
        condition["section_plan"][0]["target_chars"] = 0
        condition["section_plan"].append({"section_id":"closing", "title":"마무리", "allowed_kinds":["prose"], "target_chars":0})
        plan["entity_mention_targets"] = []
        plan["scenes"].append({"scene_id":"SC2", "section_id":"closing", "order":2,
                               "purpose":"마무리", "relation_ids":[], "outline":"처리 종료"})
        draft["segments"][-1].update(section_id="closing", scene_id="SC2")
        draft["segments"] = [draft["segments"][-1]] + draft["segments"][:-1]
        draft["relation_evidence"][0]["evidence_groups"] = [["S99"]]
        diagnosis, filled = diagnose(draft, condition, plan, values)
        self.assertTrue(diagnosis["section_order_normalized"])
        self.assertFalse(diagnosis["issues"])
        self.assertEqual(diagnosis["normalized_draft"]["segments"][-1]["sentence_id"], "S5")
        repair = diagnosis["structural_evidence_repairs"][0]
        self.assertEqual(repair["candidate_groups"], [["S1"]])
        self.assertEqual(repair["semantic_verification"], "independent_review_still_required")
        review = good_review(filled, plan)
        review["relation_checks"][0]["extractable"] = False
        self.assertFalse(check_review(review, filled, plan, condition, diagnosis["normalized_draft"])["passed"])

    def test_cross_unit_evidence_not_manufactured_and_duplicates_not_hidden(self):
        plan, condition, values, draft = fixture()
        condition.update(min_chars=0)
        condition["section_plan"][0]["target_chars"] = 0
        plan["entity_mention_targets"] = []
        # Neither existing unit contains both endpoints: metadata cannot invent a link.
        draft["segments"][0]["text"] = "<NAME:E1>의 신청을 확인했다."
        draft["segments"].append({**draft["segments"][0], "sentence_id":"S6", "text":"연락처 <MOBILE_PHONE:E2>를 확인했다."})
        draft["relation_evidence"][0]["evidence_groups"] = []
        draft["relation_evidence"][1]["evidence_groups"] = []
        draft["relation_evidence"].append(copy.deepcopy(draft["relation_evidence"][1]))
        diagnosis, _ = diagnose(draft, condition, plan, values)
        repaired = {item["relation_id"] for item in diagnosis["structural_evidence_repairs"]}
        self.assertNotIn("R1", repaired)
        self.assertIn("R2", repaired)
        codes = [issue["code"] for issue in diagnosis["issues"]]
        self.assertIn("EVIDENCE_ID", codes)
        self.assertIn("RELATION_EVIDENCE", codes)

    def test_valid_plan_covers_all_relations(self):
        plan, condition, _, _ = fixture()
        check_plan(plan, condition)

    def test_planning_schema_specialization_does_not_alias_free_text_and_ids(self):
        plan, condition, _, _ = fixture()
        schema, _ = planning_contract(condition)
        entity = schema["properties"]["entities"]["items"]["properties"]
        self.assertEqual(entity["entity_id"]["enum"][0], "E1")
        self.assertNotIn("enum", entity["context_role"])
        self.assertNotIn("enum", PLAN["properties"]["entities"]["items"]["properties"]["entity_id"])
        for relation, slot in zip(plan["relations"],relation_slots(condition)):
            relation.update(target_privacy=slot["target_privacy"])
        validate(plan, schema)

    def test_missing_owner_relation_is_rejected(self):
        plan, condition, _, _ = fixture()
        plan["scenes"][0]["relation_ids"].pop()
        with self.assertRaises(StageFailure) as raised:
            check_plan(plan, condition)
        self.assertIn("SCENE_COVERAGE", [issue.code for issue in raised.exception.issues])

    def test_plan_fingerprint_ignores_entity_ids_and_array_order(self):
        plan, _, _, _ = fixture()
        changed = copy.deepcopy(plan)
        rename = {e["entity_id"]: f"E{100-i}" for i,e in enumerate(changed["entities"])}
        for entity in changed["entities"]:
            entity["entity_id"] = rename[entity["entity_id"]]
        for relation in changed["relations"]:
            relation["source"], relation["target"] = rename[relation["source"]], rename[relation["target"]]
        changed["entities"].reverse()
        changed["relations"].reverse()
        self.assertEqual(plan_fingerprint(plan), plan_fingerprint(changed))

    def test_plan_fingerprint_keeps_graph_connectivity_of_same_role_entities(self):
        graph = {"entities": [{"entity_id": f"E{i}", "entity_type": "WORKPLACE", "context_role": "public_office"} for i in range(1,5)],
                 "scenes": [{"scene_id": "SC1", "section_id": "main", "order": 1}],
                 "relations": [{"source": "E1", "target": f"E{i}", "relation": "COLLABORATION_PARTNERSHIP",
                                "expression_mode": "single", "scene_id": "SC1", "target_privacy": "NON_PII"} for i in range(2,5)]}
        chain = copy.deepcopy(graph)
        for i, relation in enumerate(chain["relations"], 1):
            relation["source"] = f"E{i}"
        self.assertNotEqual(plan_fingerprint(graph), plan_fingerprint(chain))

    def test_mixed_incident_privacy_is_masking_group(self):
        plan, _, _, _ = fixture()
        plan["relations"].append({**plan["relations"][0], "target": "E3"})
        self.assertEqual(privacy_groups(plan)["E3"], "PII")
        self.assertEqual(privacy_groups(plan)["E4"], "NON_PII")

    def test_renderer_tracks_every_occurrence_and_excludes_references(self):
        plan, condition, values, draft = fixture()
        filled = render(draft, plan, values)
        name = next(e for e in filled["entities"] if e["entity_id"] == "E1")
        self.assertEqual(len(name["mentions"]), 3)
        self.assertEqual(len(filled["references"]), 1)
        for entity in filled["entities"]:
            for mention in entity["mentions"]:
                text = filled["sentences"][mention["sent_idx"]]["sentence"]
                self.assertEqual(text[mention["begin"]:mention["end"]], mention["form"])
        plan["entity_mention_targets"] = []
        metrics, issues = measure(filled, plan, condition)
        self.assertFalse(issues)
        self.assertEqual(metrics["entities"]["E1"]["mentions"], 3)

    def test_normalization_preserves_placeholder_type_and_particle(self):
        self.assertEqual(normalize("<NAME:E1> 는 갔다."), "<NAME:E1> 는 갔다.")
        self.assertEqual(normalize("<NAME:E1>{josa:는/은} 갔다."), "<NAME:E1>{josa:은/는} 갔다.")

    def test_three_consecutive_evidence_units_are_not_nonadjacent(self):
        _, _, _, draft = fixture()
        # All three units are necessary and contiguous: no intervening gap exists.
        draft["segments"][1]["text"] = "접수 방법을 설명했다."
        draft["segments"][2]["text"] = "<MOBILE_PHONE:E2>가 그 연락처다."
        self.assertFalse(evidence_issues([["S1", "S2", "S3"]], draft["segments"], ("E1", "E2"), {}))
        observed = observed_expression([["S1", "S2", "S3"]], {s["sentence_id"]:i for i,s in enumerate(draft["segments"])})
        self.assertEqual(observed["observed_mode"], "adjacent")

    def test_evidence_with_a_real_gap_is_nonadjacent(self):
        _, _, _, draft = fixture()
        self.assertFalse(evidence_issues([["S1", "S3"]], draft["segments"], ("E1", "E3"), {}))
        observed = observed_expression([["S3", "S1"]], {s["sentence_id"]:i for i,s in enumerate(draft["segments"])})
        self.assertEqual(observed["observed_mode"], "nonadjacent")

    def test_reversed_evidence_order_protects_actual_gap(self):
        _, _, _, draft = fixture()
        patch = {"base_draft_version": 1, "replacements": [], "refs": [], "relation_evidence_updates": [],
                 "insertions": [{"after_sentence_id": "S1", "segments": [
                     {**draft["segments"][0], "sentence_id": "S6", "text": "추가 안내를 확인했다."}]}]}
        with self.assertRaises(StageFailure) as raised:
            apply_patch(draft, patch, {"protected_adjacent_groups": [["S2", "S1"]]})
        self.assertEqual(raised.exception.issues[0].code, "PATCH_PROTECTED_GAP")

    def test_duplicate_reference_updates_are_rejected(self):
        _, _, _, draft = fixture()
        ref = copy.deepcopy(draft["refs"][0])
        patch = {"base_draft_version": 1, "replacements": [], "insertions": [],
                 "refs": [ref, {**ref, "surface": "담당자"}], "relation_evidence_updates": []}
        with self.assertRaises(StageFailure):
            apply_patch(draft, patch, {})

    def test_review_input_has_no_generator_privacy_or_intended_reference_target(self):
        plan, condition, values, draft = fixture()
        payload = review_input(render(draft, plan, values), plan, condition)
        self.assertTrue(all("target_privacy" not in r and "context_reason" not in r for r in payload["relations"]))
        self.assertTrue(all("entity_id" not in r for r in payload["references"]))
        self.assertNotIn("relation_evidence", payload)
        self.assertNotIn("expected_privacy_groups", payload)

    def test_complete_review_passes_and_missing_reference_evidence_does_not(self):
        plan, condition, values, draft = fixture()
        plan["entity_mention_targets"] = []
        filled = render(draft, plan, values)
        review = good_review(filled, plan)
        self.assertTrue(check_review(review, filled, plan, condition, draft)["passed"])
        review["reference_checks"][0]["evidence_groups"] = []
        review["reference_checks"][0]["evidence_quotes"] = []
        self.assertFalse(check_review(review, filled, plan, condition, draft)["passed"])

    def test_privacy_ambiguity_is_distinct_from_high_language_quality(self):
        plan, condition, values, draft = fixture()
        plan["entity_mention_targets"] = []
        filled = render(draft, plan, values)
        review = good_review(filled, plan)
        review["relation_checks"][0]["observed_privacy"] = "AMBIGUOUS"
        result = check_review(review, filled, plan, condition, draft)
        self.assertTrue(result["response_valid"])
        self.assertTrue(result["quality_passed"])
        self.assertFalse(result["passed"])
        self.assertEqual([i["code"] for i in result["issues"]], ["PRIVACY_AMBIGUOUS"])

    def test_review_observes_contiguous_evidence_instead_of_rejecting_plan_mismatch(self):
        plan, condition, values, draft = fixture()
        plan["entity_mention_targets"] = []
        filled = render(draft, plan, values)
        review = good_review(filled, plan)
        item = review["relation_checks"][0]
        item["single_sentence_sufficient"] = False
        item["evidence_groups"] = [["S1", "S2", "S3"]]
        item["evidence_quotes"] = [{"sentence_id": sid, "quote": filled["sentences"][i]["sentence"]}
                                  for i,sid in enumerate(("S1", "S2", "S3"))]
        result = check_review(review, filled, plan, condition, draft)
        self.assertTrue(result["passed"])
        self.assertEqual(result["expression_checks"][0]["observed_mode"], "adjacent")

    def test_annotation_uses_legacy_string_indices_and_masks_all_pii_mentions(self):
        plan, _, values, draft = fixture()
        filled = render(draft, plan, values)
        doc = annotate(filled, plan)
        for sentence in doc["sentences"]:
            self.assertIsInstance(sentence["sent_idx"], str)
            self.assertEqual(sentence["sent_seq"], list(sentence["sentence"]))
            self.assertEqual(len(sentence["labelling_seq"]), len(sentence["sentence"]))
        name = next(e for e in doc["entities"] if e["entity_id"] == "E1")
        sentences = {s["sent_idx"]: s for s in doc["sentences"]}
        for mention in name["mentions"]:
            sentence = sentences[mention["sent_idx"]]
            self.assertTrue(any(s["begin"] == mention["begin"] and s["end"] == mention["end"] for s in sentence["PII_set"]))
        # Public organization/contact values and role references remain outside PII spans.
        self.assertFalse(doc["sentences"][1]["PII_set"])
        self.assertFalse(doc["sentences"][4]["PII_set"])


if __name__ == "__main__":
    unittest.main()
