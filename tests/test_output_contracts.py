"""Regression tests for actual provider failures: reused patch IDs and runaway arrays."""
from __future__ import annotations

import copy
import unittest

from relation_pipeline.common import StageFailure
from relation_pipeline.schemas import validate
from relation_pipeline.stages.stage04_draft import document_contract
from relation_pipeline.renderer import render


class OutputContractTests(unittest.TestCase):
    def setUp(self):
        self.condition = {"length_target": 2000, "section_plan": [{"section_id": "main"}]}
        self.plan = {"entities": [{"entity_id": "E1", "entity_type": "NAME"},
                                  {"entity_id": "E2", "entity_type": "TELEPHONE"}],
                     "relations": [{"relation_id": "R1", "expression_mode": "single"}],
                     "scenes": [{"scene_id": "SC1", "section_id": "main"}]}
        self.segment = {"sentence_id": "S7", "section_id": "main", "scene_id": "SC1", "kind": "prose",
                        "text": "<NAME:E1>의 연락처는 <TELEPHONE:E2>이다."}
        self.draft = {"draft_version": 2, "segments": [self.segment, {**self.segment, "sentence_id": "S20"}],
                      "refs": [], "relation_evidence": [{"relation_id": "R1", "evidence_groups": [["S7"]]}]}

    def test_patch_accepts_existing_replacement_and_fresh_insertion_but_rejects_id_reuse(self):
        schema = document_contract(self.condition, self.plan, patch=True, draft=self.draft)
        patch = {"base_draft_version": 2, "replacements": [self.segment],
                 "insertions": [{"after_sentence_id": "S20", "segments": [{**self.segment, "sentence_id": "S21"}]}],
                 "refs": [], "relation_evidence_updates": []}
        validate(patch, schema)
        for invalid_id in ("S7", "S20"):
            reused = copy.deepcopy(patch)
            reused["insertions"][0]["segments"][0]["sentence_id"] = invalid_id
            with self.assertRaises(StageFailure):
                validate(reused, schema)
        self.assertEqual(self.draft["segments"][0]["sentence_id"], "S7")

    def test_stale_base_and_unknown_anchor_are_rejected_before_merging(self):
        schema = document_contract(self.condition, self.plan, patch=True, draft=self.draft)
        patch = {"base_draft_version": 1, "replacements": [], "insertions": [], "refs": [], "relation_evidence_updates": []}
        with self.assertRaises(StageFailure):
            validate(patch, schema)
        patch["base_draft_version"] = 2
        patch["insertions"] = [{"after_sentence_id": "S99", "segments": [{**self.segment, "sentence_id": "S21"}]}]
        with self.assertRaises(StageFailure):
            validate(patch, schema)

    def test_draft_has_an_array_budget_to_avoid_consuming_the_entire_token_limit(self):
        schema = document_contract(self.condition, self.plan)
        draft = {**self.draft, "segments": [{**self.segment, "sentence_id": f"S{i}"} for i in range(1, 501)]}
        with self.assertRaises(StageFailure) as raised:
            validate(draft, schema)
        self.assertEqual(raised.exception.issues[0].code, "SCHEMA_ARRAY_LENGTH")

    def test_bare_internal_entity_id_cannot_reach_filled_text(self):
        draft=copy.deepcopy(self.draft)
        draft['segments'][0]['text']='상대방 E2의 연락처를 확인했다.'
        values={'E1':{'value':'김민수','canonical_form':'김민수'},
                'E2':{'value':'02-123-4567','canonical_form':'02-123-4567'}}
        with self.assertRaises(StageFailure) as raised:
            render(draft,self.plan,values)
        self.assertEqual(raised.exception.issues[0].code,'RENDER_INTERNAL_ENTITY_ID')


if __name__ == "__main__":
    unittest.main()
