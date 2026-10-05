"""Regressions: observations never become repetition/placement/expression gates."""
from __future__ import annotations

import copy
import json
import tempfile
import unittest
from pathlib import Path

from relation_pipeline.common import load_config, now, read_json
from relation_pipeline.evidence import observed_expression
from relation_pipeline.renderer import render
from relation_pipeline.stages.stage02_plan import planning_input
from relation_pipeline.stages.stage05_assemble import apply_patch, diagnose
from relation_pipeline.stages.stage07_review import check_review
from relation_pipeline.statistics import snapshot
from relation_pipeline.store import Store
from test_continuation import fixture, good_review


class NaturalPolicyTests(unittest.TestCase):
    def test_uneven_many_mentions_and_one_scene_are_measured_without_repair(self):
        plan, condition, values, draft = fixture()
        condition.update(min_chars=0, distribution_policy={"pii_mention_share_bounds":[.2,.8], "min_scenes_per_group":2,"min_thirds_per_group":2})
        condition["section_plan"][0]["target_chars"] = 0
        plan["entity_mention_targets"] = [{"entity_id":"E1","min_mentions":2,"max_mentions":4,"required_scene_ids":["SC99"]}]
        draft["segments"][3]["text"] = " ".join(["<NAME:E1>"]*40) + "의 접수 내용을 확인했다."
        diagnosis, _ = diagnose(draft,condition,plan,values)
        self.assertEqual(diagnosis["issues"], [])
        distribution = diagnosis["metrics"]["distribution"]
        self.assertGreater(distribution["pii_mention_share"], .8)
        self.assertEqual(distribution["entities"]["E1"]["mentions"], 41)
        self.assertEqual(distribution["entities"]["E2"]["mentions"], 1)
        self.assertEqual(len(distribution["entities"]["E1"]["positions"]),41)

    def test_missing_required_entity_still_needs_repair(self):
        plan, condition, values, draft = fixture()
        condition["min_chars"] = 0
        condition["section_plan"][0]["target_chars"] = 0
        draft["segments"][0]["text"] = "<NAME:E1>의 신청을 확인했다."
        diagnosis, _ = diagnose(draft,condition,plan,values)
        self.assertIn("MISSING_ENTITY_MENTION", [i["code"] for i in diagnosis["issues"]])
        self.assertIn("RELATION_EVIDENCE", [i["code"] for i in diagnosis["issues"]])

    def test_minimum_alternative_and_final_order_determine_actual_mode(self):
        positions = {"S9":0,"S4":1,"S1":2,"S8":3}
        self.assertEqual(observed_expression([["S8","S9"],["S4"]],positions)["observed_mode"],"single")
        self.assertEqual(observed_expression([["S8","S9"],["S4","S1"]],positions)["observed_mode"],"adjacent")
        self.assertEqual(observed_expression([["S8","S9"]],positions)["observed_mode"],"nonadjacent")
        self.assertEqual(observed_expression([["UNKNOWN"]],positions)["observed_mode"],"unresolved")

    def test_continuation_changes_observed_mode_without_rejection(self):
        plan, condition, values, draft = fixture()
        condition["min_chars"] = 0
        condition["section_plan"][0]["target_chars"] = 0
        draft["segments"][0]["text"] = "<NAME:E1>의 개인 연락처를 확인했다."
        draft["segments"][1]["text"] += " 개인 연락처로 <MOBILE_PHONE:E2>를 등록했다"
        draft["relation_evidence"][0]["evidence_groups"] = [["S1","S2"]]
        # Use a form line here to avoid deliberately putting two prose sentences in one unit.
        draft["segments"][1]["text"] = "<WORKPLACE:E3>의 공용 메일 <EMAIL:E4>, 앞서 확인한 개인 연락처 <MOBILE_PHONE:E2>"
        diagnosis, _ = diagnose(draft,condition,plan,values)
        self.assertEqual(diagnosis["protected_adjacent_groups"], [])
        patch = {"base_draft_version":1,"replacements":[],"refs":[],"relation_evidence_updates":[],
                 "insertions":[{"after_sentence_id":"S1","segments":[{**draft["segments"][0],"sentence_id":"S6","text":"접수 순서를 확인했다."}]}]}
        updated = apply_patch(draft,patch,diagnosis)
        filled = render(updated,plan,values)
        review = good_review(filled,plan)
        item = review["relation_checks"][0]
        item.update(single_sentence_sufficient=False,evidence_groups=[["S1","S2"]],
                    evidence_quotes=[{"sentence_id":sid,"quote":next(s["sentence"] for s in filled["sentences"] if s["sentence_id"]==sid)} for sid in ("S1","S2")])
        result = check_review(review,filled,plan,condition,updated)
        self.assertTrue(result["passed"])
        self.assertEqual(result["expression_checks"][0]["observed_mode"], "nonadjacent")

    def test_inconsistent_reviewer_flag_is_audited_without_retrying_derivable_evidence(self):
        plan, condition, values, draft = fixture()
        filled = render(draft,plan,values)
        review = good_review(filled,plan)
        review["relation_checks"][0]["single_sentence_sufficient"] = False
        result = check_review(review,filled,plan,condition,draft)
        self.assertTrue(result["response_valid"])
        self.assertEqual(result["expression_checks"][0]["observed_mode"],"single")
        self.assertFalse(result["expression_checks"][0]["single_sentence_claim_consistent"])

    def test_planning_payload_has_no_expression_or_mention_allocations(self):
        _, condition, _, _ = fixture()
        payload, _ = planning_input(condition)
        encoded = json.dumps(payload)
        for field in ("expression_mode","expression_targets","entity_mention_targets","entity_repeat_policy"):
            self.assertNotIn(field, encoded)
        self.assertEqual(load_config()["mention_policy"], "natural")

    def test_statistics_uses_observation_even_when_legacy_plan_mode_differs(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            self.addCleanup(store.close)
            store.execute("INSERT INTO slots(slot_id,domain,subtype,status) VALUES('S1','support','support_ticket','accepted')")
            store.execute("INSERT INTO candidates(candidate_id,slot_id,domain,subtype,status,created_at) VALUES('C1','S1','support','support_ticket','accepted',?)", (now(),))
            store.save_artifact("C1","plan.json",{"relations":[{"relation_id":"R1","target_privacy":"PII","expression_mode":"nonadjacent"}]})
            review = {"quality":{"overall":"상","scores":{"consistency":"상","fluency":"상","suitability":"상"}},
                      "relation_checks":[{"relation_id":"R1","observed_privacy":"PII","extractable":True,"direction_supported":True,"coreference_unambiguous":True,"single_sentence_sufficient":True,"evidence_groups":[["S1"]]}]}
            store.grade("C1",1,review,True,True,True)
            store.save_artifact("C1","review_versions/review_v1.json",{"review":review,"checks":{"expression_checks":[{"relation_id":"R1","observed_mode":"single","evidence_valid":True}]}})
            result = snapshot(store,{"run_id":"fixture","mode":"offline"})
            self.assertEqual(result["selection_audit"]["accepted_observed_expression_counts"],{"single":1})
