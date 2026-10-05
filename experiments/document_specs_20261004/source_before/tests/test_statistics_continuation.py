from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from relation_pipeline.common import now
from relation_pipeline.statistics import snapshot
from relation_pipeline.store import Store


class StatisticsContinuationTests(unittest.TestCase):
    def test_retries_and_errors_do_not_inflate_terminal_candidate_forecast(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            self.addCleanup(store.close)
            for i in range(1, 5):
                store.execute("INSERT INTO slots(slot_id,domain,subtype,status) VALUES(?,?,?,?)",
                              (f"S{i}", "support", "support_ticket", "accepted" if i == 2 else "pending"))
                store.execute("INSERT INTO candidates(candidate_id,slot_id,domain,subtype,status,created_at) VALUES(?,?,?,?,?,?)",
                              (f"C{i}", f"S{i}", "support", "support_ticket", ["running", "accepted", "rejected", "error"][i-1], now()))
            first = store.begin_stage("C1", 5)
            store.finish_stage(first, "repair_needed", [{"code": "LENGTH_SHORTAGE"}])
            second = store.begin_stage("C1", 5)
            store.finish_stage(second, "passed")
            third = store.begin_stage("C3", 5)
            store.finish_stage(third, "failed", [{"code": "ENTITY_REPEAT_COUNT"}])
            low = {"quality": {"overall": "하", "scores": {"consistency": "하", "fluency": "중", "suitability": "중"}}}
            high = {"quality": {"overall": "상", "scores": {"consistency": "상", "fluency": "상", "suitability": "상"}}}
            store.grade("C1", 1, low, False, False, False)
            store.grade("C1", 2, high, True, True, True)
            result = snapshot(store, {"run_id": "fixture", "mode": "live"})
            stage = next(s for s in result["stages"] if s["stage"] == 5)
            self.assertEqual(stage["attempts"], 3)
            self.assertEqual(stage["unique_candidates"], 2)
            self.assertEqual(stage["latest_candidate_status_counts"], {"passed": 1, "failed": 1})
            self.assertEqual(stage["latest_candidate_pass_rate"], 0.5)
            self.assertEqual(result["forecast"]["observed_acceptance_rate"], 0.5)
            self.assertEqual(result["forecast"]["expected_additional_candidates"], 6)
            self.assertEqual(result["quality_latest_per_candidate"]["overall"], {"상": 1, "미판정": 3})
            self.assertEqual(stage["forecast"]["estimated_additional_entries"], 3)
            self.assertEqual(stage["forecast"]["estimated_additional_nonpasses"], 3)
            self.assertEqual(result["quality_review_attempts"], 2)

    def test_no_observations_produce_no_invented_success_rate(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            self.addCleanup(store.close)
            result = snapshot(store, {"run_id": "fixture", "mode": "offline"})
            self.assertIsNone(result["forecast"]["observed_acceptance_rate"])
            self.assertIsNone(result["forecast"]["expected_additional_candidates"])
            self.assertTrue(result["forecast"]["offline_fixture_only"])
            self.assertEqual(result["usage"], [])

    def test_candidate_rejected_after_repair_budget_is_counted_at_the_exit_stage(self):
        with tempfile.TemporaryDirectory() as directory:
            store = Store(Path(directory))
            self.addCleanup(store.close)
            store.execute("INSERT INTO slots(slot_id,domain,subtype) VALUES('S1','support','support_ticket')")
            store.execute("INSERT INTO candidates(candidate_id,slot_id,domain,subtype,created_at) VALUES('C1','S1','support','support_ticket',?)", (now(),))
            attempt = store.begin_stage("C1", 5)
            reasons = [{"code": "LENGTH_SHORTAGE", "message": "Still too short after allowed repair"},
                       {"code": "LENGTH_SHORTAGE", "message": "Second failing section"}]
            store.finish_stage(attempt, "repair_needed", reasons)
            store.finish_candidate("C1", "rejected", 5, reasons)
            result = snapshot(store, {"run_id": "repair_budget", "mode": "live"})
            stage = next(s for s in result["stages"] if s["stage"] == 5)
            self.assertEqual(stage["latest_candidate_status_counts"], {"repair_needed": 1})
            self.assertEqual(stage["final_rejections_count"], 1)
            self.assertEqual(stage["final_errors_count"], 0)
            self.assertEqual(stage["latest_candidate_pass_rate"], 0)
            self.assertEqual(result["candidate_status_counts"], {"rejected": 1})
            self.assertEqual(result["final_rejection_reasons"], {"LENGTH_SHORTAGE": 2})
            self.assertEqual(result["final_rejection_reason_candidate_counts"], {"LENGTH_SHORTAGE": 1})
            self.assertEqual(stage["reason_candidate_counts"], {"LENGTH_SHORTAGE": 1})


if __name__ == "__main__":
    unittest.main()
