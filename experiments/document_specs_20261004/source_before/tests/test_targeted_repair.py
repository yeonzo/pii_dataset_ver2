"""Regression cases from failed live repairs: filler, missing IDs and value conflicts."""
from __future__ import annotations

from copy import deepcopy
import unittest

from relation_pipeline.common import StageFailure
from relation_pipeline.repair_tasks import build_tasks, collapse_exact_boilerplate, decode_patch, evaluate_repair, normalize_sentence_ids, repair_contract, split_prose_sentences
from relation_pipeline.renderer import normalize, render
from relation_pipeline.schemas import validate
from relation_pipeline.stages.stage02_plan import check_plan, make_plan
from relation_pipeline.stages.stage05_assemble import apply_patch, diagnose
from relation_pipeline.stages.stage07_review import check_review
from relation_pipeline.value_constraints import value_group_issues
from test_continuation import fixture, good_review


class TargetedRepairTests(unittest.TestCase):
    def test_explicit_bad_sentence_cannot_be_ignored_with_null_or_unrelated_insertion(self):
        draft = deepcopy(self.draft)
        draft["segments"].append({**draft["segments"][0],"sentence_id":"S6","kind":"key_value","text":"담당 확인: 업무 처리 완료"})
        diagnosis,_ = diagnose(draft,self.condition,self.plan,self.values)
        tasks = build_tasks(draft,self.condition,self.plan,diagnosis)
        self.assertIn("S6",tasks["required_replacement_sentence_ids"])
        schema = repair_contract(draft,self.condition,self.plan,tasks)
        with self.assertRaises(StageFailure):
            validate(None,schema["properties"]["replacements"]["properties"]["S6"])

    def test_complete_sentence_repair_keeps_tokens_and_natural_word_order(self):
        draft,diagnosis,tasks,schema,wire = self.broken()
        wire["relation_repairs"]["R1"] = {"form":"sentence","text":"신청인 <NAME:E1>{josa:의} 개인 연락처는 <MOBILE_PHONE:E2>이다."}
        updated = apply_patch(draft,decode_patch(wire,schema,draft,self.condition,self.plan,tasks),diagnosis)
        after,_ = diagnose(updated,self.condition,self.plan,self.values)
        self.assertFalse(after["issues"])
        self.assertEqual(updated["segments"][0]["text"],wire["relation_repairs"]["R1"]["text"])
        wire["relation_repairs"]["R1"]["text"] = "신청인 <NAME:E1>의 개인 연락처를 확인했다."
        with self.assertRaises(StageFailure):
            decode_patch(wire,schema,draft,self.condition,self.plan,tasks)

    def test_relation_semantic_finding_repairs_body_then_passes_independent_review(self):
        draft = deepcopy(self.draft)
        _,filled = diagnose(draft,self.condition,self.plan,self.values)
        review = good_review(filled,self.plan)
        review["relation_checks"][0]["direction_supported"] = False
        review["relation_checks"][0]["reason"] = "연락처의 실제 귀속 주체가 드러나지 않는다"
        checked = check_review(review,filled,self.plan,self.condition,draft)
        self.assertTrue(checked["response_valid"])
        self.assertIn("RELATION_MEANING",[i["code"] for i in checked["issues"]])

        diagnosis = {"issues":checked["issues"],"metrics":{}}
        tasks = build_tasks(draft,self.condition,self.plan,diagnosis)
        task = next(item for item in tasks["relations"] if item["relation_id"] == "R1")
        self.assertEqual(task["operation"],"fix")
        schema = repair_contract(draft,self.condition,self.plan,tasks)
        wire = {"base_draft_version":draft["draft_version"],"insertions":[],"refs":[],
                "replacements":{sid:None for sid in schema["properties"]["replacements"]["properties"]},
                "relation_repairs":{"R1":{"form":"sentence","text":"신청인 <NAME:E1>{josa:의} 개인 연락처는 <MOBILE_PHONE:E2>이다."}},
                "relation_evidence_updates":{},"continuations":{}}
        patch = decode_patch(wire,schema,draft,self.condition,self.plan,tasks)
        repaired = apply_patch(draft,patch,{})
        _,repaired_filled = diagnose(repaired,self.condition,self.plan,self.values)
        self.assertEqual(repaired["segments"][0]["text"],wire["relation_repairs"]["R1"]["text"])
        second_review = good_review(repaired_filled,self.plan)
        second_check = check_review(second_review,repaired_filled,self.plan,self.condition,repaired)
        self.assertTrue(second_check["passed"],second_check["issues"])

    def test_long_verbatim_copies_merge_evidence_without_limiting_entity_reuse(self):
        draft = deepcopy(self.draft)
        text = "신청인 <NAME:E1>의 개인 연락처 <MOBILE_PHONE:E2>에 안내 사항을 전달하는 절차와 요청 내용을 확인하고 후속 처리 결과를 기록했다."
        draft["segments"][0]["text"] = text
        draft["segments"].append({**draft["segments"][0],"sentence_id":"S6"})
        draft["segments"].append({**draft["segments"][0],"sentence_id":"S7","text":text.replace("후속 처리 결과","추가 문의 내용")})
        draft["relation_evidence"][0]["evidence_groups"] = [["S6"]]
        result,merges = collapse_exact_boilerplate(draft)
        self.assertEqual(merges,[{"removed_sentence_id":"S6","retained_sentence_id":"S1"}])
        self.assertEqual(result["relation_evidence"][0]["evidence_groups"],[["S1"]])
        self.assertIn("S7",{s["sentence_id"] for s in result["segments"]})

    def setUp(self):
        self.plan,self.condition,self.values,self.draft = fixture()
        self.condition.update(min_chars=0,length_target=800)
        self.condition["section_plan"][0]["target_chars"] = 800

    def broken(self):
        draft = deepcopy(self.draft)
        draft["segments"][0]["text"] = "<NAME:E1>의 신청을 확인했다."
        diagnosis,_ = diagnose(draft,self.condition,self.plan,self.values)
        tasks = build_tasks(draft,self.condition,self.plan,diagnosis)
        schema = repair_contract(draft,self.condition,self.plan,tasks)
        wire = {"base_draft_version":1,"insertions":[],"refs":[],"continuations":{},
                "replacements":{sid:None for sid in schema["properties"]["replacements"]["properties"]},
                "relation_repairs":{"R1":{"form":"one_sentence","before_source":"",
                    "between_entities":"{josa:은/는} 연락처로 ","after_target":"{josa:을/를} 기재했다."}},
                "relation_evidence_updates":{}}
        return draft,diagnosis,tasks,schema,wire

    def test_actual_edit_fixes_missing_entity_and_evidence_preserving_other_text(self):
        draft,diagnosis,tasks,schema,wire = self.broken()
        self.assertEqual(tasks["missing_entities"][0]["placeholder"],"<MOBILE_PHONE:E2>")
        updated = apply_patch(draft,decode_patch(wire,schema,draft,self.condition,self.plan,tasks),diagnosis)
        after,_ = diagnose(updated,self.condition,self.plan,self.values)
        progress,guards = evaluate_repair(draft,updated,self.plan,diagnosis,after,tasks)
        self.assertFalse(after["issues"])
        self.assertFalse(guards)
        self.assertTrue(progress["structural_targets_satisfied"])
        self.assertEqual(progress["changed_sentence_ids"],["S1"])
        self.assertEqual(updated["segments"][1:],draft["segments"][1:])

    def test_filler_does_not_count_as_fixing_entity_or_relation(self):
        draft,diagnosis,tasks,schema,wire = self.broken()
        patch = {"base_draft_version":1,"refs":[],"replacements":[],"relation_evidence_updates":[],
            "insertions":[{"after_sentence_id":"S5","segments":[dict(draft["segments"][0],sentence_id="S6",text="다음 처리 순서를 확인했다.")]}]}
        updated = apply_patch(draft,patch,diagnosis)
        after,_ = diagnose(updated,self.condition,self.plan,self.values)
        progress,_ = evaluate_repair(draft,updated,self.plan,diagnosis,after,tasks)
        self.assertFalse(progress["structural_targets_satisfied"])
        self.assertEqual(progress["remaining_missing_entities"],["E2"])
        self.assertEqual(progress["remaining_invalid_relation_ids"],["R1"])
        self.assertTrue(progress["no_effective_progress"])

    def test_wire_contract_requires_every_relation_and_unique_matching_sentence_ids(self):
        _,_,_,schema,wire = self.broken()
        del wire["relation_repairs"]["R1"]
        with self.assertRaises(StageFailure):
            decode_patch(wire,schema)
        _,_,_,schema,wire = self.broken()
        wire["replacements"]["S4"] = dict(self.draft["segments"][3],sentence_id="S5")
        with self.assertRaises(StageFailure):
            decode_patch(wire,schema)

    def test_multisentence_evidence_remains_supported_without_mode_quota(self):
        draft,diagnosis,tasks,schema,wire = self.broken()
        wire["relation_repairs"]["R1"] = {"form":"linked_sentences","source_before":"",
            "source_after":"{josa:은/는} 개인 연락처를 제출했다.","bridge_sentences":["담당자는 접수 순서를 확인했다."],
            "target_before":"그 신청인이 제출한 개인 연락처는 ","target_after":"이다."}
        updated = apply_patch(draft,decode_patch(wire,schema,draft,self.condition,self.plan,tasks),diagnosis)
        after,_ = diagnose(updated,self.condition,self.plan,self.values)
        self.assertFalse(after["issues"])
        self.assertTrue(evaluate_repair(draft,updated,self.plan,diagnosis,after,tasks)[0]["structural_targets_satisfied"])
        self.assertEqual(updated["relation_evidence"][0]["evidence_groups"],[["S1","S7"]])
        self.assertIn("<MOBILE_PHONE:E2>",updated["segments"][2]["text"])

    def test_bound_repairs_allocate_ids_after_free_insertions(self):
        draft,diagnosis,tasks,schema,wire = self.broken()
        wire["insertions"] = [{"after_sentence_id":"S5","segments":[dict(draft["segments"][0],sentence_id="S6",text="접수 순서를 확인했다.")]}]
        wire["relation_repairs"]["R1"] = {"form":"linked_sentences","source_before":"",
            "source_after":"{josa:은/는} 개인 연락처를 제출했다.","bridge_sentences":[],
            "target_before":"해당 신청인의 개인 연락처는 ","target_after":"이다."}
        patch = decode_patch(wire,schema,draft,self.condition,self.plan,tasks)
        updated = apply_patch(draft,patch,diagnosis)
        self.assertEqual(updated["relation_evidence"][0]["evidence_groups"],[["S1","S7"]])
        self.assertEqual(len({s["sentence_id"] for s in updated["segments"]}),len(updated["segments"]))
        self.assertIn("S2",tasks["protected_sentence_ids"])
        self.assertNotIn("S2",tasks["reserved_sentence_ids"])

    def test_placeholder_in_a_bound_fragment_is_rejected(self):
        _,_,_,schema,wire = self.broken()
        wire["relation_repairs"]["R1"]["before_source"] = "<EMAIL:E4>"
        with self.assertRaises(StageFailure):
            decode_patch(wire,schema)

    def test_healthy_evidence_sentence_cannot_be_replaced(self):
        _,_,_,schema,wire = self.broken()
        self.assertNotIn("S2",schema["properties"]["replacements"]["properties"])
        wire["replacements"]["S2"] = dict(self.draft["segments"][1],text="연락 사항을 확인했다.")
        with self.assertRaises(StageFailure):
            decode_patch(wire,schema)

    def test_prose_split_keeps_words_and_expands_evidence_without_splitting_list_numbers(self):
        draft = deepcopy(self.draft)
        draft["segments"][0]["text"] = "1. <NAME:E1>{josa:은/는} 신청했다. 2. 개인 연락처는 <MOBILE_PHONE:E2>이다."
        fixed,changes = split_prose_sentences(draft)
        self.assertEqual([s["text"] for s in fixed["segments"][:2]],
                         ["1. <NAME:E1>{josa:은/는} 신청했다.","2. 개인 연락처는 <MOBILE_PHONE:E2>이다."])
        self.assertEqual(fixed["relation_evidence"][0]["evidence_groups"],[["S1","S6"]])
        self.assertEqual(len(changes),1)
        self.assertFalse(split_prose_sentences(fixed)[1])
        self.assertEqual(fixed["segments"][2:],draft["segments"][1:])

    def test_metadata_only_semantic_repair_preserves_original_failure_and_is_blocked(self):
        before,_ = diagnose(self.draft,self.condition,self.plan,self.values)
        before["issues"] = [{"code":"PRIVACY_AMBIGUOUS","message":"귀속이 불명확함","action":"REWRITE_SCENE","relation_id":"R1"}]
        tasks = build_tasks(self.draft,self.condition,self.plan,before)
        after,_ = diagnose(self.draft,self.condition,self.plan,self.values)
        progress,guards = evaluate_repair(self.draft,self.draft,self.plan,before,after,tasks)
        self.assertFalse(progress["all_code_checks_passed"])
        self.assertEqual({i["code"] for i in guards},{"PRIVACY_AMBIGUOUS","REPAIR_BODY_UNCHANGED"})

    def test_duplicate_id_repair_preserves_all_text_and_does_not_guess_evidence(self):
        draft = deepcopy(self.draft)
        draft["segments"][1]["sentence_id"] = "S1"
        fixed,changes = normalize_sentence_ids(draft)
        self.assertEqual([s["text"] for s in fixed["segments"]],[s["text"] for s in draft["segments"]])
        self.assertEqual(len({s["sentence_id"] for s in fixed["segments"]}),len(fixed["segments"]))
        self.assertEqual(fixed["relation_evidence"][0]["evidence_groups"],[])
        self.assertEqual(len(changes),1)

    def test_missing_entities_reported_even_when_bad_josa_prevents_render(self):
        draft = deepcopy(self.draft)
        draft["segments"][0]["text"] = "<NAME:E1>{josa:unknown} 신청을 확인했다."
        diagnosis,_ = diagnose(draft,self.condition,self.plan,self.values)
        self.assertIn("JOSA_MARKER",[i["code"] for i in diagnosis["issues"]])
        self.assertIn("E2",[i["entity_id"] for i in diagnosis["issues"] if i["code"] == "MISSING_ENTITY_MENTION"])

    def test_single_particle_marker_is_normalized_by_code(self):
        self.assertEqual(normalize("<NAME:E1>{josa:와} 상담했다."),"<NAME:E1>{josa:과/와} 상담했다.")
        self.assertEqual(normalize("<NAME:E1>{josa:의/의} 상담이다."),"<NAME:E1>의 상담이다.")

    def test_continuation_contract_requires_actual_new_characters_and_keeps_original_body(self):
        initial,_ = diagnose(self.draft,self.condition,self.plan,self.values)
        self.condition["min_chars"] = initial["metrics"]["rendered_chars"]+300
        diagnosis,_ = diagnose(self.draft,self.condition,self.plan,self.values)
        tasks = build_tasks(self.draft,self.condition,self.plan,diagnosis)
        schema = repair_contract(self.draft,self.condition,self.plan,tasks)
        wire = {"base_draft_version":1,"insertions":[],"refs":[],"replacements":{},
                "relation_repairs":{},"relation_evidence_updates":{},"continuations":{"SC1":"추가 확인했다."}}
        short = apply_patch(self.draft,decode_patch(wire,schema,self.draft,self.condition,self.plan,tasks),diagnosis)
        self.assertIn("LENGTH_SHORTAGE",[i["code"] for i in diagnose(short,self.condition,self.plan,self.values)[0]["issues"]])
        wire["continuations"]["SC1"] = "\x00"*300
        with self.assertRaises(StageFailure):
            decode_patch(wire,schema,self.draft,self.condition,self.plan,tasks)
        wire["continuations"]["SC1"] = "처리 절차를 확인했다. "*30
        patch = decode_patch(wire,schema,self.draft,self.condition,self.plan,tasks)
        updated = apply_patch(self.draft,patch,diagnosis)
        after,_ = diagnose(updated,self.condition,self.plan,self.values)
        self.assertFalse(after["issues"])
        self.assertEqual(updated["segments"][:5],self.draft["segments"])

    def test_form_lines_are_split_without_dropping_entities(self):
        draft = deepcopy(self.draft)
        draft["segments"][0].update(kind="item",text="신청인: <NAME:E1>\n개인 연락처: <MOBILE_PHONE:E2>")
        fixed,changes = split_prose_sentences(draft)
        self.assertEqual(fixed["relation_evidence"][0]["evidence_groups"],[["S1","S6"]])
        self.assertEqual([s["text"] for s in fixed["segments"][:2]],["신청인: <NAME:E1>","개인 연락처: <MOBILE_PHONE:E2>"])
        self.assertEqual(len(changes),1)


class ValueConstraintRepairTests(unittest.TestCase):
    def broken(self):
        plan,condition,_,_ = fixture()
        plan["entities"].append(dict(plan["entities"][2],entity_id="E6"))
        plan["relations"].append(dict(plan["relations"][1],relation_id="R4",source="E6"))
        plan["scenes"][0]["relation_ids"].append("R4")
        plan["slot_constraints"] = [{"constraint_id":"K1","kind":"same_organization","entity_ids":["E3","E6"],"field":"","allowed_values":[]}]
        condition.update(relation_count=4,non_pii_relation_target=3)
        return plan,condition

    def test_group_conflict_is_detected_during_plan_validation_with_entity_details(self):
        plan,condition = self.broken()
        with self.assertRaises(StageFailure) as raised:
            check_plan(plan,condition)
        issue = next(i for i in raised.exception.issues if i.code=="VALUE_GROUP_TYPE_CONFLICT")
        self.assertIn("E3",issue.message)
        self.assertIn("E6",issue.message)
        self.assertIn("K1",issue.message)

    def test_group_only_repair_cannot_drop_entities_or_replace_graph(self):
        plan,condition = self.broken()
        feedback = [i.json() for i in value_group_issues(plan)]
        corrected = deepcopy(plan)
        corrected = {"slot_groups":{e["entity_id"]:"" for e in plan["entities"]},"slot_constraints":[]}
        class FixedClient:
            def request(self,*args):
                self.payload = args[-2]
                return deepcopy(corrected)
        client = FixedClient()
        result = make_plan(client,condition,feedback,plan)
        self.assertEqual(client.payload["existing_plan"],plan)
        self.assertEqual(result["relations"],plan["relations"])
        corrected["relations"] = []
        with self.assertRaises(StageFailure) as raised:
            make_plan(client,condition,feedback,plan)
        self.assertEqual(raised.exception.issues[0].code,"SCHEMA_KEYS")
        self.assertEqual(raised.exception.plan_attempt["relations"],plan["relations"])

    def test_transitive_and_implicit_groups_are_checked_before_value_selection(self):
        plan,_ = self.broken()
        plan["slot_constraints"] = []
        plan["entities"][2]["slot_group"] = "office"
        plan["entities"][-1]["slot_group"] = "office"
        self.assertEqual(value_group_issues(plan)[0].code,"VALUE_GROUP_TYPE_CONFLICT")

        for e in plan["entities"]:
            e["slot_group"] = ""
        plan["slot_constraints"] = [
            {"constraint_id":"K1","kind":"same_organization","entity_ids":["E3","E4"],"field":"","allowed_values":[]},
            {"constraint_id":"K2","kind":"same_organization","entity_ids":["E4","E6"],"field":"","allowed_values":[]}]
        self.assertEqual(value_group_issues(plan)[0].code,"VALUE_GROUP_TYPE_CONFLICT")

    def test_incompatible_allowed_values_are_detected_before_value_selection(self):
        plan,_,_,_ = fixture()
        plan["slot_constraints"] = [
            {"constraint_id":"K1","kind":"occupation","entity_ids":["E1"],"field":"occupation","allowed_values":["교사"]},
            {"constraint_id":"K2","kind":"occupation","entity_ids":["E1"],"field":"occupation","allowed_values":["의사"]}]
        self.assertEqual(value_group_issues(plan)[0].code,"VALUE_ALLOWED_CONFLICT")
