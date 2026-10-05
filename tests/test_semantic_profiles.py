"""Scenario graph selection must keep role direction and global coverage feasible."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from relation_pipeline.common import DOMAINS, load_config
from relation_pipeline.coverage import RELATION_TYPES, candidate_triples, eligible_targets
from relation_pipeline.formats import allowed_triples
from relation_pipeline.planning_seed import seed_plan
from relation_pipeline.stages.stage01_condition import select_condition
from relation_pipeline.stages.stage02_plan import check_plan
from relation_pipeline.store import Store


CASES = (
    ("career_education", "recommendation"),
    ("contract", "service"),
    ("financial", "fraud_report"),
    ("legal", "mediation_application"),
    ("medical", "registration"),
    ("support", "refund_request"),
)


class ScenarioGraphTests(unittest.TestCase):
    def test_six_smoke_subtypes_produce_valid_scenario_graphs(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            self.addCleanup(store.close)
            cfg = load_config()
            cfg.update(run_id="scenario_fixture", graph_policy="scenario_v1", relation_count_range=[4, 6], selection={})
            cfg["relation_coverage"] = {**cfg["relation_coverage"], "max_required_per_document": 1}
            for domain, subtype in CASES:
                slot = {"slot_id":f"{domain}_001", "domain":domain, "subtype":subtype}
                condition = select_condition(cfg, store, slot, slot["slot_id"]+"_c001", 1)
                self.assertTrue(condition["graph_profile_applied"])
                plan = seed_plan(condition, allowed_triples(domain))
                check_plan(plan, condition)
                self.assertEqual(len(plan["relations"]), condition["relation_count"])
                self.assertTrue(set(condition["required_relation_types"]) <= {r["relation"] for r in plan["relations"]})
                if (domain, subtype) == ("financial", "fraud_report"):
                    types = {e["entity_id"]:e["entity_type"] for e in plan["entities"]}
                    self.assertNotIn("SCHOOL", {types[r["source"]] for r in plan["relations"]})
                if (domain, subtype) == ("medical", "registration"):
                    self.assertNotIn("CASE_AND_INCIDENT_RELATION", {r["relation"] for r in plan["relations"]})

    def test_recommendation_guidance_direction_is_recommender_to_candidate(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            self.addCleanup(store.close)
            cfg = load_config()
            cfg.update(run_id="scenario_fixture", graph_policy="scenario_v1", relation_count_range=[4, 4], selection={})
            slot = {"slot_id":"career_education_001", "domain":"career_education", "subtype":"recommendation"}
            condition = select_condition(cfg,store,slot,"career_education_001_c001",1)
            condition["coverage_requirements"] = [{"relation":"GUIDANCE_SUPPORT", "privacy":"PII"}]
            condition["required_relation_types"] = ["GUIDANCE_SUPPORT"]
            plan = seed_plan(condition,allowed_triples("career_education"))
            check_plan(plan,condition)
            by_role = {p["role"]:p["name_entity_id"] for p in plan["persons"]}
            guidance = [r for r in plan["relations"] if r["relation"] == "GUIDANCE_SUPPORT"]
            self.assertEqual(len(guidance),1)
            self.assertEqual((guidance[0]["source"],guidance[0]["target"]),
                             (by_role["recommender"],by_role["candidate"]))
            self.assertNotIn(["NAME","GUIDANCE_SUPPORT","SCHOOL"],candidate_triples(condition,"PII"))

    def test_nineteen_relation_types_remain_reachable_in_full_dataset(self):
        cfg = load_config()
        cfg.update(graph_policy="scenario_v1", domains=list(DOMAINS), selection={})
        self.assertEqual(len(RELATION_TYPES),19)
        self.assertEqual([], [r for r in RELATION_TYPES if not eligible_targets(cfg,r)])


if __name__ == "__main__":
    unittest.main()
