"""Partitioning preserves the paired graph and the full generation budget."""
from copy import deepcopy
import unittest

from experiments.split_generation import merge, partition
from relation_pipeline.common import StageFailure
from relation_pipeline.schemas import DRAFT
from relation_pipeline.stages.stage04_draft import document_contract
from test_continuation import fixture


class ComparisonTests(unittest.TestCase):
    def pair(self):
        plan, condition, values, draft = fixture()
        condition.update(length_target=1600,min_chars=1500,topic="연락 안내")
        section = condition["section_plan"][0]
        condition["section_plan"] = [dict(section,section_id="first",target_chars=800),
                                     dict(section,section_id="second",target_chars=800)]
        plan["relations"][1]["scene_id"] = "SC2"
        plan["scenes"][0].update(section_id="first",relation_ids=["R1","R3"])
        plan["scenes"].append(dict(plan["scenes"][0],scene_id="SC2",section_id="second",order=2,relation_ids=["R2"]))
        return plan, condition

    def test_partition_preserves_every_relation_and_total_budget(self):
        plan, condition = self.pair()
        before = deepcopy((plan,condition))
        parts = partition(condition,plan)
        self.assertEqual({r["relation_id"] for p in parts for r in p["plan"]["relations"]},{"R1","R2","R3"})
        self.assertEqual(sum(p["condition"]["length_target"] for p in parts),1600)
        full = document_contract(condition,plan)["properties"]["segments"]
        for bound in ("minItems","maxItems"):
            self.assertEqual(sum(p["schema"]["properties"]["segments"][bound] for p in parts),full[bound])
        contract = document_contract(condition,plan)
        for part in parts:
            self.assertEqual(part["schema"]["properties"]["segments"]["items"]["properties"]["text"],
                             contract["properties"]["segments"]["items"]["properties"]["text"])
            self.assertEqual(part["schema"]["properties"]["refs"]["items"]["properties"]["entity_id"],
                             contract["properties"]["refs"]["items"]["properties"]["entity_id"])
        self.assertEqual(before,(plan,condition))

    def test_merge_preserves_cross_batch_evidence_and_rejects_id_collision(self):
        _,_,_,draft = fixture()
        part1 = deepcopy(draft)
        part2 = {"draft_version":1,"segments":[dict(draft["segments"][0],sentence_id="S1000")],
                 "refs":[],"relation_evidence":[{"relation_id":"R4","evidence_groups":[["S1","S1000"]]}]}
        joined = merge([part1,part2],DRAFT)
        self.assertEqual(joined["relation_evidence"][-1]["evidence_groups"],[["S1","S1000"]])
        part2["segments"][0]["sentence_id"] = "S1"
        with self.assertRaises(StageFailure):
            merge([part1,part2],DRAFT)

    def test_prefers_mixed_batches_without_changing_privacy_labels(self):
        plan, condition = self.pair()
        extra = deepcopy(plan["relations"][0])
        extra.update(relation_id="R4",scene_id="SC2")
        plan["relations"].append(extra)
        plan["scenes"][1]["relation_ids"].append("R4")
        parts = partition(condition,plan)
        self.assertTrue(all(p["privacy_counts"]["PII"] and p["privacy_counts"]["NON_PII"] for p in parts))

    def test_saved_plan_metadata_must_be_removed_before_strict_plan_validation(self):
        from relation_pipeline.schemas import PLAN
        from relation_pipeline.stages.stage02_plan import check_plan
        plan, condition, _, _ = fixture()
        saved = dict(plan,plan_fingerprint="audit",expected_privacy_groups={"E1":"PII"})
        with self.assertRaises(StageFailure):
            check_plan(saved,condition)
        check_plan({key:saved[key] for key in PLAN["properties"]},condition)


if __name__ == "__main__":
    unittest.main()
