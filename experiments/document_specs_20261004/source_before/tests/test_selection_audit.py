"""Selection-bias reporting must distinguish cases, response failures and revisions."""
from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path

from relation_pipeline.common import now
from relation_pipeline.statistics import export, snapshot
from relation_pipeline.store import Store


class SelectionAuditTests(unittest.TestCase):
    def test_repaired_ambiguity_and_context_requirements_are_tracked_without_new_calls(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            self.addCleanup(store.close)
            for cid, status, mode, privacy in (("C1", "accepted", "nonadjacent", "NON_PII"),
                                                ("C2", "rejected", "single", "PII"),
                                                ("C3", "rejected", "adjacent", "PII")):
                store.execute("INSERT INTO slots(slot_id,domain,subtype,status) VALUES(?,?,?,?)",
                              (cid, "support", "support_ticket", status if status == "accepted" else "pending"))
                store.execute("INSERT INTO candidates(candidate_id,slot_id,domain,subtype,status,created_at) VALUES(?,?,?,?,?,?)",
                              (cid, cid, "support", "support_ticket", status, now()))
                store.save_artifact(cid, "plan.json", {"relations": [{"relation_id": "R1",
                                    "target_privacy": privacy, "expression_mode": mode}]})

            def judgment(cid, version, privacy, groups, valid=True, expression=True):
                review = {"quality": {"overall": "상", "scores": {"consistency": "상", "fluency": "중", "suitability": "상"}},
                          "relation_checks": [{"relation_id": "R1", "observed_privacy": privacy,
                          "extractable": True, "direction_supported": True, "coreference_unambiguous": True,
                          "single_sentence_sufficient": len(groups[0]) == 1, "evidence_groups": groups, "reason": "fixture"}]}
                store.grade(cid, version, review, valid, privacy != "AMBIGUOUS", True)
                if valid:
                    store.save_artifact(cid, f"review_versions/review_v{version}.json", {
                        "review": review, "checks": {"expression_checks": [{"relation_id": "R1", "passed": expression}]},
                        "draft_revision": version, "reviewed_body_hash": f"body{version}"})

            judgment("C1", 1, "AMBIGUOUS", [["S1", "S3"]])
            judgment("C1", 2, "NON_PII", [["S1", "S3"]])
            judgment("C2", 1, "AMBIGUOUS", [["S1"]])
            judgment("C2", 2, "AMBIGUOUS", [["S1"]])
            judgment("C3", 1, "PII", [["S1", "S2"]])
            judgment("C3", 2, "PII", [["S1", "S2"]], valid=False)
            result = export(store, {"run_id": "selection_fixture", "mode": "live"})
            audit = result["selection_audit"]
            self.assertEqual(audit["reviewed_candidates"], 3)
            self.assertEqual(audit["valid_latest_review_candidates"], 2)
            self.assertEqual(audit["invalid_latest_review_candidates"], 1)
            self.assertEqual(audit["latest_ambiguous_candidates"], 1)
            self.assertEqual(audit["latest_ambiguity_candidate_rate"], 0.5)
            self.assertEqual(audit["ever_ambiguous_candidates"], 2)
            self.assertEqual(audit["ever_ambiguous_candidate_outcomes"], {"accepted": 1, "rejected": 1})
            self.assertEqual(audit["accepted_confirmed_expression_counts"], {"nonadjacent": 1})
            self.assertEqual(audit["accepted_confirmed_multisentence_relations"], 1)
            self.assertEqual(audit["accepted_candidates_with_confirmed_multisentence_relations"], 1)
            self.assertEqual(store.rows("SELECT * FROM api_calls"), [])
            with (store.run_dir / "statistics" / "review_relations.csv").open(encoding="utf-8-sig") as stream:
                rows = list(csv.DictReader(stream))
            self.assertEqual(len(rows), 5)
            self.assertEqual(rows[1]["minimum_evidence_sentence_count"], "2")
            self.assertEqual(rows[1]["reviewed_body_hash"], "body2")

    def test_unreviewed_data_has_no_invented_ambiguity_rate(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            self.addCleanup(store.close)
            result = snapshot(store, {"run_id": "empty", "mode": "offline", "relation_count_range": [8, 12]})
            self.assertIsNone(result["selection_audit"]["latest_ambiguity_candidate_rate"])
            self.assertEqual(result["dataset_design"]["classification"], "controlled_synthetic_documents")
            self.assertFalse(result["dataset_design"]["frequency_representative"])
            self.assertEqual(result["dataset_design"]["configured_controls"]["relation_count_range"], [8, 12])


if __name__ == "__main__":
    unittest.main()
