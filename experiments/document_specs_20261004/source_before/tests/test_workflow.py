from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from relation_pipeline.common import TYPES, Issue, StageFailure, atomic_json, digest, load_config, read_json
from relation_pipeline.offline import OfflineClient
from relation_pipeline.runner import Runner
from relation_pipeline.stages import stage00_prepare, stage03_values, stage08_accept
from relation_pipeline.store import Store
from relation_pipeline.validation import validate_document


def personas():
    rows = []
    for i in range(1, 4):
        values = {"NAME": ["가온", "나래", "다온"][i-1], "ADDRESS": f"서울시 가상구 예시로 {i}",
                  "WORKPLACE": f"예시센터{i}", "DEPARTMENT": f"예시부서{i}", "POSITION": "담당자", "SCHOOL": f"예시학교{i}",
                  "MAJOR": "예시학과", "AGE": "30", "DATE_OF_BIRTH": "1996-01-01", "MOBILE_PHONE": f"010-0000-000{i}",
                  "TELEPHONE": f"02-000-000{i}", "EMAIL": f"fixture{i}@example.invalid", "RRN": f"960101-100000{i}",
                  "PASSPORT_NUMBER": f"M0000000{i}", "DRIVER_LICENSE_NUMBER": f"11-00-00000{i}-11", "VEHICLE_NUMBER": f"00가000{i}",
                  "BANK_ACCOUNT_NUMBER": f"000-000-00000{i}", "CARD_NUMBER": f"0000-0000-0000-000{i}", "uuid": f"fixture-{i}"}
        assert set(TYPES) <= values.keys()
        rows.append(values)
    return rows


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        pool = self.root / "pool.json"
        atomic_json(pool, personas())
        self.cfg = load_config()
        self.cfg['generation_flow'] = 'legacy'  # Regression coverage for frozen legacy runs.
        self.cfg["relation_coverage"]["enabled"] = False
        self.cfg.update(run_id="workflow_fixture", mode="offline", domains=["financial"], target_per_domain=1,
                        selection={"subtype": "wire_transfer"}, pool_path=str(pool), reference_dataset=None,
                        relation_count_range=[3, 3], resource_hashes={"fixture": "frozen"})
        self.cfg["config_hash"] = digest(self.cfg)
        self.store = Store(self.root / "runs" / "workflow_fixture")
        self.addCleanup(self.store.close)
        atomic_json(self.store.run_dir / "run_config.json", self.cfg)
        self.store.execute("INSERT INTO slots(slot_id,domain,subtype) VALUES('financial_001','financial','wire_transfer')")
        self.output_patch = patch.object(stage08_accept, "ROOT", self.root)
        self.output_patch.start()
        self.addCleanup(self.output_patch.stop)

    def run_fixture(self, scenario="normal", **kwargs):
        runner = Runner(self.store, OfflineClient(self.cfg, self.store, scenario))
        with contextlib.redirect_stdout(io.StringIO()):
            return runner.run(max_candidates=1, **kwargs)

    def test_all_eight_stages_commit_legacy_schema(self):
        result = self.run_fixture()
        self.assertEqual(result["candidate_status_counts"], {"accepted": 1})
        self.assertTrue(all(s["latest_candidate_status_counts"] == {"passed": 1} for s in result["stages"]))
        accepted = self.store.rows("SELECT * FROM accepted")[0]
        self.assertTrue(validate_document(read_json(Path(accepted["document_path"]))) ["passed"])
        self.assertEqual(len(self.store.rows("SELECT * FROM api_calls")), 3)

    def test_short_document_is_continued_once_not_regenerated(self):
        result = self.run_fixture("short_then_repair")
        self.assertEqual(result["candidate_status_counts"], {"accepted": 1})
        tasks = [r["task"] for r in self.store.rows("SELECT * FROM api_calls ORDER BY id")]
        self.assertEqual(tasks, ["plan", "draft", "repair", "review"])
        stage = next(s for s in result["stages"] if s["stage"] == 5)
        self.assertEqual(stage["attempt_status_counts"]["repair_needed"], 1)
        self.assertEqual(stage["latest_candidate_status_counts"], {"passed": 1})
        self.assertEqual(result["repair_audit"]["evaluated_attempts"],1)
        self.assertEqual(result["repair_audit"]["all_code_checks_passed"],1)
        self.assertTrue((self.store.run_dir/"statistics"/"repair_progress.csv").is_file())

    def test_format_failure_uses_existing_document_patch_without_another_draft(self):
        class FirstBadFormat(OfflineClient):
            reviews = 0
            def repair(self,payload):
                result = super().repair(payload)
                old = next(s for s in payload["draft"]["segments"] if s["kind"] == "prose"
                           and s["sentence_id"] not in payload["repair_tasks"]["protected_sentence_ids"])
                result["replacements"] = [{**old,"text":"확인 기록: "+old["text"]}]
                return result
            def request(self,*args):
                result = super().request(*args)
                if args[2] == "review":
                    self.reviews += 1
                    if self.reviews == 1:
                        result["format_adherence"]["document_format_supported"] = False
                return result
        runner = Runner(self.store,FirstBadFormat(self.cfg,self.store))
        with contextlib.redirect_stdout(io.StringIO()):
            result = runner.run(max_candidates=1)
        self.assertEqual(result["candidate_status_counts"],{"accepted":1})
        tasks = [r["task"] for r in self.store.rows("SELECT task FROM api_calls ORDER BY id")]
        self.assertEqual(tasks,["plan","draft","review","repair","review"])

    def test_semantic_privacy_failure_is_rejected_without_relations_deleted(self):
        result = self.run_fixture("review_privacy_failure")
        self.assertEqual(result["candidate_status_counts"], {"rejected": 1})
        self.assertIn("RELATION_MEANING", result["final_rejection_reasons"])
        self.assertEqual(self.store.rows("SELECT * FROM accepted"), [])
        candidate = self.store.rows("SELECT * FROM candidates")[0]["candidate_id"]
        plan = read_json(self.store.run_dir / "candidates" / candidate / "plan.json")
        self.assertEqual(len(plan["relations"]), 3)
        self.assertEqual(len(self.store.rows("SELECT * FROM api_calls WHERE task IN ('draft','repair')")), self.cfg["max_document_actions"])

    def test_invalid_review_schema_retains_grades_and_retries_once(self):
        result = self.run_fixture("review_schema_then_retry")
        self.assertEqual(result["candidate_status_counts"], {"accepted": 1})
        reviews = self.store.rows("SELECT * FROM reviews ORDER BY id")
        self.assertEqual([r["response_valid"] for r in reviews], [0, 1])
        self.assertEqual([r["overall"] for r in reviews], ["상", "상"])
        self.assertEqual(len(self.store.rows("SELECT * FROM api_calls WHERE task='review'")), 2)

    def test_review_budget_exhaustion_keeps_the_actionable_response_failure(self):
        class ReviewThenCap(OfflineClient):
            reviews = 0
            def request(self,*args):
                if args[2] != "review":
                    return super().request(*args)
                self.reviews += 1
                if self.reviews == 1:
                    response = super().request(*args)
                    # Corrupt the model's evidence selection, not code-owned quotes.
                    response["relation_checks"][0]["evidence_groups"] = []
                    return response
                raise StageFailure([Issue("CANDIDATE_CALL_LIMIT","request cap reached","STOP_CANDIDATE")])
        runner = Runner(self.store,ReviewThenCap(self.cfg,self.store))
        with contextlib.redirect_stdout(io.StringIO()):
            result = runner.run(max_candidates=1)
        reasons = set(result["final_rejection_reasons"])
        self.assertEqual(result["candidate_status_counts"],{"rejected":1})
        self.assertIn("REVIEW_MISSING_EVIDENCE",reasons)
        self.assertIn("CANDIDATE_CALL_LIMIT",reasons)

    def test_ambiguity_rejection_keeps_high_grades_and_does_not_count_repairs_twice(self):
        result = self.run_fixture("review_ambiguous")
        self.assertEqual(result["candidate_status_counts"], {"rejected": 1})
        self.assertIn("PRIVACY_AMBIGUOUS", result["final_rejection_reasons"])
        self.assertEqual(result["quality_latest_per_candidate"]["overall"], {"상": 1})
        audit = result["selection_audit"]
        self.assertEqual(audit["reviewed_candidates"], 1)
        self.assertEqual(audit["ever_ambiguous_candidates"], 1)
        self.assertEqual(audit["ever_ambiguous_candidate_outcomes"], {"rejected": 1})
        self.assertEqual(audit["latest_ambiguous_candidates"], 1)
        self.assertEqual(audit["accepted_confirmed_expression_counts"], {})
        self.assertTrue((self.store.run_dir / "statistics" / "review_relations.csv").is_file())

    def test_resume_uses_checkpoints_without_double_counting_or_new_plan_call(self):
        result = self.run_fixture(stop_after=3)
        self.assertEqual(result["candidate_status_counts"], {"paused": 1})
        candidate = self.store.rows("SELECT * FROM candidates")[0]["candidate_id"]
        # Model the checkpoint-write/database-update crash window.
        self.store.execute("UPDATE stage_attempts SET status='running',finished_at=NULL WHERE candidate_id=? AND stage=1", (candidate,))
        result = self.run_fixture()
        self.assertEqual(result["candidate_status_counts"], {"accepted": 1})
        self.assertEqual(len(self.store.rows("SELECT * FROM api_calls WHERE task='plan'")), 1)
        self.assertEqual(len(self.store.rows("SELECT * FROM stage_attempts WHERE stage=1")), 1)
        self.assertEqual(self.store.rows("SELECT status FROM stage_attempts WHERE stage=1")[0]["status"], "passed")

    def test_invalid_selection_fails_before_creating_run_files(self):
        with patch.object(stage00_prepare, "ROOT", self.root):
            with self.assertRaises(StageFailure) as raised:
                stage00_prepare.prepare(load_config(), "bad_selection", ["financial"], 1, {"variant": "narrative"})
        self.assertEqual(raised.exception.issues[0].code, "VARIANT_SELECTION")
        self.assertFalse((self.root / "runs" / "bad_selection").exists())

    def test_unambiguous_personal_attributes_share_persona_without_merging_public_nodes(self):
        plan = {"entities": [{"entity_id": "E1", "entity_type": "NAME", "slot_group": ""},
                             {"entity_id": "E2", "entity_type": "MOBILE_PHONE", "slot_group": ""},
                             {"entity_id": "E3", "entity_type": "DATE_OF_BIRTH", "slot_group": ""},
                             {"entity_id": "E4", "entity_type": "WORKPLACE", "slot_group": ""}],
                "relations": [{"source": "E1", "target": "E2", "target_privacy": "PII"},
                              {"source": "E1", "target": "E3", "target_privacy": "PII"}], "slot_constraints": []}
        values = stage03_values.select_values(plan, {"candidate_id": "fixture"}, personas())
        self.assertEqual(values["E1"]["source_uuid"], values["E2"]["source_uuid"])
        self.assertEqual(values["E1"]["source_uuid"], values["E3"]["source_uuid"])
        self.assertNotEqual(values["E1"]["constraint_group"], values["E4"]["constraint_group"])


if __name__ == "__main__":
    unittest.main()
