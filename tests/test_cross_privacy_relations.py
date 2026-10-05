"""NON_PII relations with one PII endpoint: participant organisation bridges and party-reference links."""
from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from relation_pipeline.common import StageFailure, atomic_json, digest, load_config, read_json
from relation_pipeline.entity_semantics import entity_write_guide
from relation_pipeline.offline import OfflineClient
from relation_pipeline.planning_seed import BRIDGE_FACTS, BRIDGE_TARGET_TYPES, ORG_TYPES, organization_bridges, seed_plan
from relation_pipeline.reference_people import LINK_RELATIONS, PROFILES, is_party_link
from relation_pipeline.renderer import render
from relation_pipeline.runner import Runner
from relation_pipeline.schemas import PLAN
from relation_pipeline.stages import stage00_prepare, stage01_condition, stage08_accept
from relation_pipeline.stages.stage02_plan import check_plan, planning_contract, planning_input, privacy_groups
from relation_pipeline.stages.stage03_values import select_values
from relation_pipeline.stages.stage08_accept import annotate
from relation_pipeline.store import Store
from test_coverage_privacy_persons import coverage_pool


class CrossPrivacyFixture(unittest.TestCase):
    def planned(self, domain, subtype, selection=None, ordinal=1, **overrides):
        """Condition and checked seed plan from the real condition stage, without API or pool access."""
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        cfg = load_config()
        cfg["relation_coverage"]["enabled"] = False
        cfg.update(overrides)
        cfg.update(run_id="cross_fixture", mode="offline", domains=[domain], target_per_domain=1,
                   selection={"subtype": subtype, **(selection or {})}, reference_dataset=None, resource_hashes={"fixture": "frozen"})
        cfg["config_hash"] = digest(cfg)
        store = Store(Path(directory.name) / "runs" / "cross_fixture")
        self.addCleanup(store.close)
        slot = {"slot_id": f"{domain}_001", "domain": domain, "subtype": subtype}
        condition = stage01_condition.select_condition(cfg, store, slot, f"{domain}_001_c{ordinal:03d}", ordinal)
        plan = seed_plan(condition, planning_contract(condition)[1])
        return condition, plan

    @staticmethod
    def checked(plan, condition):
        check_plan({key: plan[key] for key in PLAN["properties"]}, condition)


class OrganizationBridgeTests(CrossPrivacyFixture):
    def test_disabled_configuration_keeps_personal_and_public_graphs_apart(self):
        condition, plan = self.planned("career_education", "resume_form", organization_bridge_range=[0, 0], reference_person_rate=0)
        self.assertNotIn("organization_bridge_target", condition)
        self.assertEqual(organization_bridges(plan), [])
        groups = privacy_groups(plan)
        self.assertTrue(all(groups[r["source"]] == groups[r["target"]] for r in plan["relations"]))

    def test_bridge_starts_from_the_participants_organisation_and_ends_at_public_only_information(self):
        condition, plan = self.planned("career_education", "resume_form", organization_bridge_range=[1, 1], relation_count_range=[4, 4])
        self.assertEqual(condition["organization_bridge_target"], 1)
        self.checked(plan, condition)
        self.assertEqual([r["relation_id"] for r in plan["relations"]], ["R1", "R2", "R3", "R4"])
        bridge, = organization_bridges(plan)
        types = {e["entity_id"]: e["entity_type"] for e in plan["entities"]}
        groups = privacy_groups(plan)
        self.assertEqual(bridge["target_privacy"], "NON_PII")
        self.assertIn(types[bridge["source"]], ORG_TYPES)
        self.assertIn(types[bridge["target"]], BRIDGE_TARGET_TYPES)
        self.assertEqual((groups[bridge["source"]], groups[bridge["target"]]), ("PII", "NON_PII"))
        owner = next(r for r in plan["relations"] if r["target_privacy"] == "PII" and r["target"] == bridge["source"])
        self.assertEqual(types[owner["source"]], "NAME")

    def test_public_value_comes_from_another_row_and_only_the_organisation_is_masked(self):
        condition, plan = self.planned("career_education", "resume_form", organization_bridge_range=[1, 1], relation_count_range=[4, 4])
        bridge, = organization_bridges(plan)
        values = select_values(plan, condition, coverage_pool())
        name = condition["person_slots"][0]["name_entity_id"]
        self.assertEqual(values[bridge["source"]]["source_uuid"], values[name]["source_uuid"])
        self.assertNotEqual(values[bridge["target"]]["source_uuid"], values[name]["source_uuid"])
        types = {e["entity_id"]: e["entity_type"] for e in plan["entities"]}
        segments = [{"sentence_id": f"S{i}", "section_id": plan["scenes"][0]["section_id"], "scene_id": "SC1", "kind": "prose",
                     "text": f"<{types[r['source']]}:{r['source']}>의 확인 대상은 <{types[r['target']]}:{r['target']}>이다."}
                    for i, r in enumerate(plan["relations"], 1)]
        document = annotate(render({"draft_version": 1, "segments": segments, "refs": [], "relation_evidence": []}, plan, values), plan)
        masked = {span["form"] for sentence in document["sentences"] for span in sentence["PII_set"]}
        self.assertIn(values[bridge["source"]]["value"], masked)
        self.assertNotIn(values[bridge["target"]]["value"], masked)
        label = next(r["privacy_label"] for r in document["relations"] if r["entity"] == bridge["source"] and r["target_entity"] == bridge["target"])
        self.assertEqual(label, "NON_PII")

    def test_plan_request_and_writing_guide_state_that_the_value_belongs_to_the_organisation(self):
        condition, plan = self.planned("career_education", "resume_form", organization_bridge_range=[1, 1], relation_count_range=[4, 4])
        bridge, = organization_bridges(plan)
        payload, _ = planning_input(condition)
        seeded = {r["relation_id"]: r["context_reason"] for r in payload["seed_plan"]["relations"]}
        types = {e["entity_id"]: e["entity_type"] for e in plan["entities"]}
        self.assertEqual(seeded[bridge["relation_id"]], BRIDGE_FACTS[types[bridge["target"]]])
        self.assertTrue(all(not text for rid, text in seeded.items() if rid != bridge["relation_id"]))
        guide = {g["entity_id"]: g["write_rule"] for g in entity_write_guide(plan, condition["domain"])}
        self.assertIn(f":{bridge['source']}>", guide[bridge["target"]])
        self.assertIn("당사자 본인의", guide[bridge["target"]])

    def test_subtype_without_participant_organisations_gets_no_target(self):
        condition, plan = self.planned("support", "refund_request", organization_bridge_range=[1, 1])
        self.assertNotIn("organization_bridge_target", condition)
        self.checked(plan, condition)
        self.assertEqual(organization_bridges(plan), [])

    def test_plan_that_misses_the_recorded_count_is_rejected(self):
        condition, plan = self.planned("career_education", "resume_form", organization_bridge_range=[1, 1], relation_count_range=[4, 4])
        with self.assertRaises(StageFailure) as raised:
            self.checked(plan, {**condition, "organization_bridge_target": 2})
        self.assertIn("ORGANIZATION_BRIDGE_COUNT", [issue.code for issue in raised.exception.issues])


class PartyReferenceLinkTests(CrossPrivacyFixture):
    def linked(self, profile):
        return self.planned("career_education", "cover_letter", {"reference_profile": profile},
                            reference_link_policy="party_link_v1", relation_count_range=[3, 3])

    def test_actual_party_cites_each_registered_reference_kind_with_a_non_pii_relation(self):
        for profile, registered in PROFILES.items():
            condition, plan = self.linked(profile)
            self.checked(plan, condition)
            link, = [r for r in plan["relations"] if is_party_link(plan, condition, r)]
            kinds = {p["name_entity_id"]: p["context_kind"] for p in plan["persons"]}
            groups = privacy_groups(plan)
            self.assertEqual(link["relation"], LINK_RELATIONS[registered["context_kind"]])
            self.assertEqual((kinds[link["source"]], kinds[link["target"]]), ("actual_party", registered["context_kind"]))
            self.assertEqual((groups[link["source"]], groups[link["target"]]), ("PII", "NON_PII"))
            self.assertEqual(condition["reference_context"]["party_link"]["relation"], link["relation"])

    def test_plan_request_keeps_the_registered_fact_and_the_link_fact(self):
        condition, plan = self.linked("marie_curie_education")
        link = next(r for r in plan["relations"] if is_party_link(plan, condition, r))
        payload, _ = planning_input(condition)
        seeded = {r["relation_id"]: r["context_reason"] for r in payload["seed_plan"]["relations"]}
        self.assertIn("공개 전기", seeded[link["relation_id"]])
        self.assertEqual(sum(bool(text) for text in seeded.values()), 2)

    def test_same_graph_is_rejected_when_the_policy_is_off(self):
        condition, plan = self.linked("marie_curie_education")
        disabled = {key: value for key, value in condition.items() if key != "reference_link_policy"}
        with self.assertRaises(StageFailure) as raised:
            self.checked(plan, disabled)
        codes = [issue.code for issue in raised.exception.issues]
        self.assertIn("NAME_CONTEXT_POLICY", codes)
        self.assertIn("REFERENCE_FACT_SCOPE", codes)

    def test_link_cannot_carry_another_relation_or_a_pii_label(self):
        condition, plan = self.linked("fictional_student")
        link = next(r for r in plan["relations"] if is_party_link(plan, condition, r))
        link["relation"] = "PERSONAL_RELATIONSHIP"
        with self.assertRaises(StageFailure) as raised:
            self.checked(plan, condition)
        self.assertIn("NAME_CONTEXT_POLICY", [issue.code for issue in raised.exception.issues])

    def test_reference_document_has_no_party_link_when_the_policy_is_none(self):
        condition, plan = self.planned("career_education", "cover_letter", {"reference_profile": "fictional_student"}, reference_link_policy="none")
        self.assertNotIn("party_link", condition["reference_context"])
        self.assertFalse(any(is_party_link(plan, condition, r) for r in plan["relations"]))


class RandomReferenceTests(CrossPrivacyFixture):
    def test_rate_decides_whether_an_eligible_document_gets_a_registered_reference_person(self):
        condition, plan = self.planned("career_education", "cover_letter", reference_person_rate=1.0, reference_link_policy="party_link_v1")
        self.assertIn(condition["reference_profile"], PROFILES)
        self.checked(plan, condition)
        self.assertEqual(sum(is_party_link(plan, condition, r) for r in plan["relations"]), 1)
        condition, plan = self.planned("career_education", "cover_letter", reference_person_rate=0)
        self.assertNotIn("reference_profile", condition)
        self.assertTrue(all(p["context_kind"] == "actual_party" for p in plan["persons"]))

    def test_unsupported_document_types_never_get_one(self):
        for domain, subtype in (("career_education", "resume_form"), ("support", "refund_request")):
            condition, _ = self.planned(domain, subtype, reference_person_rate=1.0)
            self.assertNotIn("reference_profile", condition)

    def test_explicit_selection_wins_and_the_draw_is_repeatable(self):
        condition, _ = self.planned("career_education", "cover_letter", {"reference_profile": "marie_curie_education"}, reference_person_rate=1.0)
        self.assertEqual(condition["reference_profile"], "marie_curie_education")
        drawn = [self.planned("career_education", "cover_letter", ordinal=2, reference_person_rate=1.0)[0]["reference_profile"] for _ in range(2)]
        self.assertEqual(drawn[0], drawn[1])

    def test_shipped_defaults_mix_both_relation_kinds_at_random(self):
        cfg = load_config()
        self.assertEqual(cfg["organization_bridge_range"], [0, 2])
        self.assertEqual((cfg["reference_person_rate"], cfg["reference_link_policy"]), (0.1, "party_link_v1"))
        with_person = sum("reference_profile" in self.planned("career_education", "cover_letter", ordinal=k, reference_person_rate=0.5)[0] for k in range(1, 21))
        self.assertTrue(0 < with_person < 20)
        targets = {self.planned("career_education", "resume_form", ordinal=k)[0].get("organization_bridge_target", 0) for k in range(1, 21)}
        self.assertEqual(targets, {0, 1, 2})


class CrossPrivacyWorkflowTests(unittest.TestCase):
    def test_offline_document_with_both_relation_kinds_is_accepted_and_masked_on_one_side(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pool = root / "pool.json"
            atomic_json(pool, coverage_pool())
            cfg = load_config()
            cfg["relation_coverage"]["enabled"] = False
            cfg.update(pool_path=str(pool), reference_dataset=None, organization_bridge_range=[1, 1], reference_link_policy="party_link_v1",
                       relation_count_range=[5, 5], non_pii_relation_fraction_range=[0.6, 0.6])
            selection = {"subtype": "cover_letter", "reference_profile": "marie_curie_education"}
            with patch.object(stage00_prepare, "ROOT", root), patch.object(stage08_accept, "ROOT", root), \
                    patch.object(stage00_prepare, "resource_hashes", return_value={"fixture": "frozen"}):
                store = stage00_prepare.prepare(cfg, "cross_workflow", ["career_education"], 1, selection, "offline")
                self.addCleanup(store.close)
                runner = Runner(store, OfflineClient(read_json(store.run_dir / "run_config.json"), store))
                with contextlib.redirect_stdout(io.StringIO()):
                    result = runner.run(max_candidates=1)
                self.assertEqual(result["candidate_status_counts"], {"accepted": 1}, result["final_rejection_reasons"])
                document = read_json(Path(store.rows("SELECT * FROM accepted")[0]["document_path"]))
        masked = {span["form"] for sentence in document["sentences"] for span in sentence["PII_set"]}
        forms = {e["entity_id"]: e["canonical_form"] for e in document["entities"]}
        mixed = [r for r in document["relations"] if (forms[r["entity"]] in masked) != (forms[r["target_entity"]] in masked)]
        self.assertTrue(all(r["privacy_label"] == "NON_PII" and forms[r["entity"]] in masked for r in mixed))
        self.assertEqual({(r["entity_type"], r["target_entity_type"] == "NAME") for r in mixed if r["entity_type"] == "NAME"}, {("NAME", True)})
        self.assertTrue(any(r["entity_type"] in ORG_TYPES and r["target_entity_type"] in BRIDGE_TARGET_TYPES for r in mixed))
        self.assertIn("마리 퀴리", forms.values())
        self.assertNotIn("마리 퀴리", masked)


if __name__ == "__main__":
    unittest.main()
