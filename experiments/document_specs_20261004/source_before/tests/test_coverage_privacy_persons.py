"""Final coverage, shared definitions, ownership and localized semantic repair."""
from __future__ import annotations

import contextlib
import copy
import io
import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from relation_pipeline.common import DOMAINS, StageFailure, atomic_json, file_hash, load_config, read_json
from relation_pipeline.coverage import RELATION_TYPES, candidate_triples, coverage_state, eligible_targets, index_final_relations
from relation_pipeline.formats import CATALOG, allowed_triples
from relation_pipeline.offline import OfflineClient
from relation_pipeline.persons import CAREER_EDUCATION_ROLES, ROLE_IDS, ROLE_LABELS, RANGES, party_range, person_plan_issues, role_ids, select_people
from relation_pipeline.planning_seed import seed_plan
from relation_pipeline.prompt_inputs import compact_issues
from relation_pipeline.privacy import POLICY_HASH, privacy_input
from relation_pipeline.repair_tasks import build_tasks
from relation_pipeline.renderer import render
from relation_pipeline.runner import Runner
from relation_pipeline.schemas import validate
from relation_pipeline.stages import stage00_prepare, stage08_accept
from relation_pipeline.stages.stage02_plan import check_plan, constraint_repair_input, make_plan, planning_contract, planning_input
from relation_pipeline.stages.stage04_draft import draft_input
from relation_pipeline.stages.stage05_assemble import diagnose, repair_input
from relation_pipeline.stages.stage07_review import check_review, review_input
from relation_pipeline.statistics import snapshot
from relation_pipeline.store import Store
from relation_pipeline.stages.stage01_condition import select_condition
import test_commit_continuation
from test_continuation import fixture, good_review
from test_workflow import personas


def coverage_pool():
    rows = []
    for i in range(1,25):
        row = copy.deepcopy(personas()[0])
        row.update(uuid=f"coverage-{i}",NAME="가온"+chr(0xac00+i),EMAIL=f"coverage{i}@example.invalid",
            MOBILE_PHONE=f"010-0000-{i:04d}",TELEPHONE=f"02-000-{i:04d}",RRN=f"960101-1{i:06d}",
            PASSPORT_NUMBER=f"M{i:08d}",DRIVER_LICENSE_NUMBER=f"11-00-{i:06d}-11",
            BANK_ACCOUNT_NUMBER=f"000-000-{i:06d}",CARD_NUMBER=f"0000-0000-0000-{i:04d}",VEHICLE_NUMBER=f"00가{i:04d}")
        for typ in ("WORKPLACE","DEPARTMENT","SCHOOL"):
            row[typ] += str(i)
        rows.append(row)
    return rows


class PolicyAndPersonTests(unittest.TestCase):
    def test_subtype_topic_dictionary_is_not_a_random_document_title(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            self.addCleanup(store.close)
            cfg = load_config()
            cfg.update(run_id="topic_fixture",selection={})
            for subtype in CATALOG["domains"]["financial"]:
                slot = {"slot_id":"financial_001","domain":"financial","subtype":subtype}
                condition = select_condition(cfg,store,slot,"financial_001_c001",1)
                self.assertEqual(condition["topic"],CATALOG["topics"]["financial"][subtype])

    def test_person_roles_match_party_semantics_in_source_specs(self):
        self.assertEqual(role_ids("career_education","scholarship_application"),["applicant","guarantor"])
        self.assertEqual(role_ids("medical","insurance_claim"),["insured","claimant"])
        self.assertEqual(party_range("contract","accident_rear"),(2,3))
        self.assertEqual(party_range("contract","lease"),(2,2))

    def test_every_catalog_subtype_has_explicit_person_count_and_roles(self):
        self.assertEqual(set(CAREER_EDUCATION_ROLES),set(CATALOG["domains"]["career_education"]))
        self.assertEqual(set(RANGES),set(CATALOG["domains"]))
        self.assertEqual(set(ROLE_IDS),set(CATALOG["domains"]))
        for domain,subtype_specs in CATALOG["domains"].items():
            subtypes = set(subtype_specs)
            self.assertEqual(set(RANGES[domain]),subtypes,domain)
            self.assertEqual(set(ROLE_IDS[domain]),subtypes,domain)
            for subtype in subtypes:
                lo,hi = party_range(domain,subtype)
                roles = role_ids(domain,subtype)
                self.assertGreaterEqual(lo,1)
                self.assertLessEqual(lo,hi)
                self.assertGreaterEqual(len(roles),hi,(domain,subtype))
                self.assertTrue(set(roles) <= set(ROLE_LABELS),(domain,subtype))

    def test_unknown_document_subtype_does_not_receive_silent_person_defaults(self):
        with self.assertRaisesRegex(ValueError,"Missing named-person range"):
            party_range("career_education","new_unregistered_type")
        with self.assertRaisesRegex(ValueError,"Missing named-person roles"):
            role_ids("career_education","new_unregistered_type")

    def test_repeated_feedback_is_grouped_without_losing_targets(self):
        issues = [{"code":"TEXT_CONSISTENCY","message":"반복 문장을 교정한다","action":"REWRITE_SCENE", "sentence_id":f"S{i}","relation_id":"R1"} for i in range(1,101)]
        compact = compact_issues(issues)
        self.assertEqual(len(compact),1)
        self.assertEqual(len(compact[0]["targets"]),100)
        self.assertEqual(compact[0]["targets"][-1]["sentence_id"],"S100")

    def test_planner_returns_only_context_and_code_keeps_graph_and_ownership(self):
        _,condition,_,_ = fixture()
        payload,schema = planning_input(condition)
        seed = copy.deepcopy(payload["seed_plan"])
        class ContextClient:
            def request(self,*args):
                return {"relation_contexts":{r["relation_id"]:{"context_reason":"기존 귀속을 유지하고 상담 접수에서 사용한다","scene_id":r["scene_id"]} for r in seed["relations"]},
                    "scene_notes":{s["scene_id"]:{"purpose":"접수 처리","outline":"연락과 업무 경과를 확인한다"} for s in seed["scenes"]}}
        plan = make_plan(ContextClient(),condition)
        for field in ("persons","person_entity_links","entities","slot_constraints"):
            self.assertEqual(plan[field],seed[field])
        for original,result in zip(seed["relations"],plan["relations"]):
            for field in ("relation_id","source","target","relation","target_privacy"):
                self.assertEqual(original[field],result[field])
        with self.assertRaises(StageFailure):
            validate(seed,schema)

    def test_supported_extra_relationship_is_localized_and_not_lost_without_evidence(self):
        plan,condition,values,draft = fixture()
        filled = render(draft,plan,values)
        review = good_review(filled,plan)
        review["missing_relations"] = [{"source":"E1","target":"E2","relation":"INFORMATION_GOVERNANCE","observed_privacy":"PII",
            "evidence_groups":[["S1"]],"evidence_quotes":[{"sentence_id":"S1","quote":filled["sentences"][0]["sentence"]}]}]
        checks = check_review(review,filled,plan,condition,draft)
        issue = next(i for i in checks["issues"] if i["code"] == "UNPLANNED_RELATIONS")
        self.assertEqual(issue["sentence_id"],"S1")
        self.assertIn("INFORMATION_GOVERNANCE",issue["message"])
        review["missing_relations"][0]["evidence_groups"] = []
        checks = check_review(review,filled,plan,condition,draft)
        self.assertFalse(checks["passed"])
        self.assertFalse(checks["response_valid"])

    def test_every_required_type_can_be_planned_with_registered_people(self):
        cfg = load_config()
        cfg.update(domains=list(DOMAINS), selection={})
        self.assertEqual(len(RELATION_TYPES), 19)
        for relation in RELATION_TYPES:
            domain, subtype = eligible_targets(cfg, relation)[0]
            _, hi = party_range(domain, subtype)
            # Pick the maximum supported count to exercise multi-person ownership.
            people = select_people(domain, subtype, random.Random(0), minimum=hi)
            condition = {"candidate_id":"seed_"+relation, "domain":domain,
                "allowed_personal_types":CATALOG["domains"][domain][subtype]["personal_types"],
                "allowed_public_types":["WORKPLACE","DEPARTMENT","SCHOOL","POSITION","MAJOR","ADDRESS","EMAIL","TELEPHONE","MOBILE_PHONE","BANK_ACCOUNT_NUMBER"],
                "relation_count":8,"pii_relation_target":4,"non_pii_relation_target":4,"non_pii_only_min":2,
                "section_plan":[{"section_id":"main","title":"본문","allowed_kinds":["prose"]}],
                "required_relation_types":[relation], **people}
            label = "NON_PII" if any(t[1] == relation for t in candidate_triples(condition,"NON_PII")) else "PII"
            condition["coverage_requirements"] = [{"relation":relation,"privacy":label}]
            plan = seed_plan(condition, allowed_triples(domain))
            check_plan(plan, condition)
            schema, _ = planning_contract(condition)
            validate(plan, schema)
            self.assertIn(relation, {r["relation"] for r in plan["relations"]})
            self.assertEqual(len(plan["persons"]), hi)

    def test_same_privacy_definition_reaches_all_model_tasks(self):
        plan, condition, values, draft = fixture()
        condition.update(length_target=800,min_chars=0)
        condition["section_plan"][0]["target_chars"] = 0
        diagnosis, filled = diagnose(draft, condition, plan, values)
        payloads = [planning_input(condition)[0], draft_input(condition,plan),
            repair_input(draft,condition,plan,diagnosis), review_input(filled,plan,condition),
            constraint_repair_input(condition,[],plan)[0]]
        for payload in payloads:
            self.assertEqual(payload["privacy_policy"], privacy_input())
        payloads[0]["privacy_policy"]["version"] = "mutated"
        self.assertNotEqual(privacy_input()["version"], "mutated")
        self.assertEqual(len(POLICY_HASH),64)

    def test_person_roles_remain_independent_in_reviewer_input(self):
        plan, condition, values, draft = fixture()
        payload = review_input(render(draft,plan,values),plan,condition)
        self.assertNotIn("persons",payload)
        self.assertNotIn("person_entity_links",payload)
        self.assertNotIn("target_privacy",str(payload["relations"]))
        self.assertNotIn("name_entity_id",str(payload["person_expectation"]))
        review = good_review(render(draft,plan,values),plan)
        review["person_checks"]["observed_persons"][0]["role"] = "recipient"
        checks = check_review(review,render(draft,plan,values),plan,condition,draft)
        self.assertTrue(checks["response_valid"])
        issue = next(i for i in checks["issues"] if i["code"] == "PERSON_ROLE_MEANING")
        tasks = build_tasks(draft,condition,plan,{"issues":[issue]})
        self.assertEqual([r["relation_id"] for r in tasks["relations"] if r["operation"] == "fix"],["R1"])
        self.assertTrue(next(r for r in tasks["relations"] if r["relation_id"] == "R1")["errors"])

    def test_wrong_owner_and_missing_person_are_rejected(self):
        plan, condition, _, _ = fixture()
        changed = copy.deepcopy(plan)
        changed["persons"] = []
        self.assertIn("PERSON_NAME_COVERAGE",[i.code for i in person_plan_issues(changed,condition)])
        changed = copy.deepcopy(plan)
        owned = next(link for link in changed["person_entity_links"] if link["entity_id"] == "E2")
        owned["relation_ids"] = ["R2"]
        self.assertIn("PERSON_LINK_RELATION",[i.code for i in person_plan_issues(changed,condition)])
        condition["required_relation_types"] = ["PERSONAL_RELATIONSHIP"]
        with self.assertRaises(StageFailure) as raised:
            check_plan(plan,condition)
        self.assertIn("REQUIRED_RELATION_MISSING",[i.code for i in raised.exception.issues])

    def test_localized_fluency_error_releases_its_evidence_for_actual_repair(self):
        plan, condition, values, draft = fixture()
        filled = render(draft,plan,values)
        review = good_review(filled,plan)
        review["quality"] = {"overall":"하","scores":{"consistency":"상","fluency":"하","suitability":"상"},"reason":"명백한 문장 오류"}
        review["text_issues"] = [{"kind":"fluency","sentence_ids":["S1"],"relation_ids":["R1"],
            "reason":"조사 오류","fix_instruction":"연락처의 귀속을 유지하고 조사를 수정한다"}]
        checks = check_review(review,filled,plan,condition,draft)
        self.assertFalse(checks["passed"])
        self.assertTrue(checks["response_valid"])
        tasks = build_tasks(draft,condition,plan,{"issues":checks["issues"]})
        self.assertNotIn("S1",tasks["protected_sentence_ids"])
        self.assertIn("S2",tasks["protected_sentence_ids"])
        self.assertEqual(next(r for r in tasks["relations"] if r["relation_id"] == "R1")["replacement_sentence_id"],"S1")

    def test_low_quality_grade_without_a_repair_target_is_not_sent_to_generation(self):
        plan, condition, values, draft = fixture()
        filled = render(draft,plan,values)
        review = good_review(filled,plan)
        review["quality"] = {"overall":"하","scores":{"consistency":"상","fluency":"하","suitability":"상"},"reason":"문장 오류"}
        checks = check_review(review,filled,plan,condition,draft)
        self.assertFalse(checks["response_valid"])
        self.assertIn("REVIEW_QUALITY_TARGET",[i["code"] for i in checks["issues"]])

    def test_expression_mode_uses_cited_evidence_not_a_duplicate_reviewer_flag(self):
        plan, condition, values, draft = fixture()
        filled = render(draft,plan,values)
        review = good_review(filled,plan)
        review["relation_checks"][0]["single_sentence_sufficient"] = False
        checks = check_review(review,filled,plan,condition,draft)
        expression = next(e for e in checks["expression_checks"] if e["relation_id"] == "R1")
        self.assertTrue(checks["response_valid"])
        self.assertEqual(expression["observed_mode"],"single")
        self.assertFalse(expression["single_sentence_claim_consistent"])
        self.assertTrue(expression["evidence_valid"])

    def test_repair_context_excludes_distant_filler_and_uses_full_id_range(self):
        plan, condition, _, draft = fixture()
        draft["segments"] += [{**draft["segments"][-1],"sentence_id":f"S{i}","text":"업무 처리 이력을 확인했다."} for i in range(6,21)]
        payload = repair_input(draft,condition,plan,{"issues":[{"code":"RELATION_MEANING","relation_id":"R1","action":"REWRITE_SCENE","message":"개인 귀속 미명시"}]})
        self.assertNotIn("S20",{s["sentence_id"] for s in payload["draft"]["segments"]})
        self.assertEqual(payload["new_sentence_id_start"],"S21")


class FinalCoverageTests(unittest.TestCase):
    def test_commit_counts_only_final_relations_once_and_keeps_global_requirement(self):
        harness = test_commit_continuation.CommitContinuationTests(methodName="test_commit_is_idempotent_and_manifest_matches_ledger")
        harness.setUp()
        self.addCleanup(harness.doCleanups)
        cfg = load_config()
        cfg.update(run_id="fixture", mode="offline")
        atomic_json(harness.store.run_dir/"run_config.json",cfg)
        self.assertEqual(coverage_state(harness.store,cfg)["covered_type_count"],0)
        first = harness.commit()
        harness.commit()
        document = read_json(Path(first["document_path"]))
        with harness.store.db:
            index_final_relations(harness.store,"support_001_c001",document,file_hash(Path(first["document_path"])))
        counts = {r["relation"]:r for r in coverage_state(harness.store,cfg)["counts"]}
        self.assertEqual(counts["CONTACT_ASSOCIATION"]["accepted_relations"],2)
        self.assertEqual(counts["CONTACT_ASSOCIATION"]["accepted_documents"],1)
        self.assertEqual(counts["CONTACT_ASSOCIATION"]["PII"],1)
        manifest = read_json(harness.store.run_dir/"manifest.json")
        self.assertTrue(manifest["quota_complete"])
        self.assertEqual(manifest["status"],"incomplete")
        self.assertEqual(len(manifest["relation_coverage"]["missing_types"]),17)

    def test_offline_six_domain_workflow_completes_all_nineteen_final_types(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pool = root/"pool.json"
            atomic_json(pool,coverage_pool())
            cfg = load_config()
            cfg.update(pool_path=str(pool), reference_dataset=None, max_candidates_per_slot=1)
            with patch.object(stage00_prepare,"ROOT",root),patch.object(stage08_accept,"ROOT",root),patch.object(stage00_prepare,"resource_hashes",return_value={"fixture":"frozen"}):
                store = stage00_prepare.prepare(cfg,"coverage_fixture",target=1,mode="offline")
                self.addCleanup(store.close)
                runner = Runner(store,OfflineClient(read_json(store.run_dir/"run_config.json"),store))
                with contextlib.redirect_stdout(io.StringIO()):
                    result = runner.run(max_candidates=24)
                self.assertTrue(result["completion"]["complete"],result["final_rejection_reasons"])
                self.assertEqual(result["relation_coverage"]["covered_type_count"],19)
                for row in result["relation_coverage"]["counts"]:
                    self.assertGreaterEqual(row["accepted_relations"],1)
                self.assertTrue(result["person_audit"])
                self.assertTrue((store.run_dir/"statistics/persons.csv").is_file())
                for accepted in store.rows("SELECT * FROM accepted"):
                    doc = read_json(Path(accepted["document_path"]))
                    self.assertEqual(set(doc),{"sentences","entities","relations"})

    def test_subset_preflight_reports_unreachable_types_without_dropping_them(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pool = root/"pool.json"
            atomic_json(pool,personas())
            cfg = load_config()
            cfg.update(pool_path=str(pool),reference_dataset=None)
            with patch.object(stage00_prepare,"ROOT",root),patch.object(stage00_prepare,"resource_hashes",return_value={"fixture":"frozen"}):
                store = stage00_prepare.prepare(cfg,"subset_fixture",["support"],target=1,mode="offline")
                self.addCleanup(store.close)
                state = coverage_state(store,cfg)
                self.assertEqual(state["required_type_count"],19)
                self.assertFalse(state["complete"])
                self.assertTrue(read_json(store.run_dir/"coverage_preflight.json")["unreachable_types"])


if __name__ == "__main__":
    unittest.main()
