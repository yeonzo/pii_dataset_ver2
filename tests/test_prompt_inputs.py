"""Input projection must preserve task semantics without audit/answer leakage."""
from __future__ import annotations

import copy
import unittest

from relation_pipeline.renderer import render
from relation_pipeline.schemas import validate
from relation_pipeline.stages.stage02_plan import check_plan, planning_input
from relation_pipeline.stages.stage04_draft import draft_input
from relation_pipeline.stages.stage05_assemble import repair_input
from relation_pipeline.stages.stage07_review import review_input
from test_continuation import fixture


class PromptInputTests(unittest.TestCase):
    def setUp(self):
        self.plan, self.condition, self.values, self.draft = fixture()
        self.condition.update(run_id="audit-run", slot_id="audit-slot", condition_version=4,
                              topic_id="audit-topic", topic="배송 지연 문의", config_hash="audit-hash",
                              length_target=1600, min_chars=1500, name_context_policy="local-policy",
                              unexpected_metadata="local-only")
        self.condition["section_plan"][0].update(target_chars=1600, required=True)
        self.plan.update(expected_privacy_groups={"E1":"PII"}, plan_fingerprint="audit-graph",
                         value_map={"E1":{"value":"LOCAL_VALUE_MUST_NOT_REACH_GENERATOR"}})

    def assert_no_audit_fields(self, condition):
        for field in ("run_id", "slot_id", "candidate_id", "condition_version", "topic_id", "config_hash", "unexpected_metadata"):
            self.assertNotIn(field, condition)

    def test_planner_has_exact_requirements_and_feasible_seed_after_projection(self):
        payload, schema = planning_input(self.condition)
        self.assert_no_audit_fields(payload["condition"])
        self.assertEqual(payload["requirements"], {"total_relations":3,"pii_relations":1,"non_pii_relations":2,"non_pii_only_nodes_min":2})
        self.assertNotIn("relation_count", payload["condition"])
        self.assertEqual(payload["condition"]["allowed_personal_types"],self.condition["allowed_personal_types"])
        self.assertEqual(payload["condition"]["topic"], "배송 지연 문의")
        self.assertEqual(set(schema["properties"]),{"relation_contexts","scene_notes"})
        self.assertEqual(set(schema["properties"]["relation_contexts"]["properties"]),{r["relation_id"] for r in payload["seed_plan"]["relations"]})
        check_plan(payload["seed_plan"],self.condition)

    def test_draft_preserves_graph_sections_and_endpoint_tokens_without_values(self):
        before = copy.deepcopy(self.plan)
        payload = draft_input(self.condition,self.plan)
        self.assert_no_audit_fields(payload["condition"])
        self.assertEqual(payload["plan"]["relations"], self.plan["relations"])
        self.assertEqual(payload["condition"]["section_plan"], self.condition["section_plan"])
        self.assertEqual(payload["placeholder_map"]["E1"], "<NAME:E1>")
        self.assertEqual(payload["relation_write_slots"][0]["target_placeholder"], "<MOBILE_PHONE:E2>")
        guides={x["entity_id"]:x for x in payload["entity_write_guide"]}
        self.assertIn("자연인의 이름",guides["E1"]["type_meaning"])
        self.assertIn("휴대전화 번호",guides["E2"]["type_meaning"])
        self.assertEqual(guides["E2"]["relations"][0]["counterpart"]["placeholder"],"<NAME:E1>")
        self.assertIn("특정 개인에게 귀속",guides["E2"]["write_rule"])
        self.assertNotIn("expected_privacy_groups", payload["plan"])
        self.assertNotIn("plan_fingerprint", payload["plan"])
        self.assertNotIn("value_map", payload["plan"])
        payload["plan"]["entities"][0]["context_role"] = "changed_in_request"
        self.assertEqual(self.plan, before)

    def test_repair_preserves_errors_and_length_targets_without_observation_goals(self):
        issues = [{"code":"RELATION_EVIDENCE","relation_id":"R1","action":"REGENERATE_SCENE"}]
        metrics = {"rendered_chars":900,"min_chars":1500,"shortage_chars":600,
                   "section_chars":{"main":900},"section_shortages":{"main":700},
                   "distribution":{"pii_mention_share":.99,"entities":{"E1":{"mentions":20}}}}
        diagnosis = {"issues":issues,"metrics":metrics,"normalized_draft":self.draft,
                     "suspected_unplanned_endpoint_pairs":[{"entity_a":"E1","entity_b":"E3"}],
                     "structural_evidence_repairs":[{"relation_id":"R1"}]}
        payload = repair_input(self.draft,self.condition,self.plan,diagnosis)
        self.assert_no_audit_fields(payload["condition"])
        self.assertEqual(payload["new_sentence_id_start"],"S6")
        self.assertEqual(payload["diagnosis"]["issues"], issues)
        self.assertEqual(payload["diagnosis"]["metrics"]["section_shortages"],{"main":700})
        self.assertEqual(set(payload["diagnosis"]),{"issues","metrics"})
        self.assertEqual(payload["entity_write_guide"][0]["placeholder"],"<NAME:E1>")
        self.assertNotIn("distribution",payload["diagnosis"]["metrics"])
        self.assertIn("distribution",diagnosis["metrics"])

    def test_reviewer_still_gets_actual_mentions_without_plan_answers(self):
        payload = review_input(render(self.draft,self.plan,self.values),self.plan,self.condition)
        self.assertEqual(payload["relations"][0],{"relation_id":"R1","source":"E1","target":"E2","relation":"CONTACT_ASSOCIATION"})
        self.assertEqual(len(payload["entities"][0]["mentions"]),3)
        self.assertTrue(all("entity_id" not in ref for ref in payload["references"]))
        for field in ("plan", "context_reason", "expected_privacy_groups", "relation_evidence", "plan_fingerprint"):
            self.assertNotIn(field, payload)
