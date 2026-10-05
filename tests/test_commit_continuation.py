from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from relation_pipeline.common import StageFailure, atomic_json, now, read_json
from relation_pipeline.distribution import measure
from relation_pipeline.renderer import render
from relation_pipeline.runner import Runner
from relation_pipeline.stages import stage08_accept
from relation_pipeline.store import Store
from test_continuation import fixture, good_review


class AcceptingDedup:
    def plan_check(self, *args):
        return {"passed": True}

    def document_check(self, *args):
        return {"structure": {"fingerprint": "fixture-structure"}, "normalized_text": "fixture normalized text"}


class CommitContinuationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.store = Store(self.root / "runs" / "fixture")
        self.addCleanup(self.store.close)
        self.store.execute("INSERT INTO slots(slot_id,domain,subtype) VALUES('support_001','support','support_ticket')")
        self.store.execute("INSERT INTO candidates(candidate_id,slot_id,domain,subtype,created_at) VALUES(?,?,?,?,?)",
                           ("support_001_c001", "support_001", "support", "support_ticket", now()))
        self.cfg = {"run_id": "fixture", "schema_version": "1.0", "privacy_policy_version": "1.0",
                    "generation_model": "gpt-4o-mini", "review_model": "gpt-5-mini", "mode": "offline"}
        self.plan, self.condition, values, self.draft = fixture()
        self.plan.update(entity_mention_targets=[], plan_fingerprint="fixture-plan")
        self.condition.update(candidate_id="support_001_c001", slot_id="support_001")
        self.filled = render(self.draft, self.plan, values)
        self.review = good_review(self.filled, self.plan)
        distribution, issues = measure(self.filled, self.plan, self.condition)
        self.assertFalse(issues)
        self.checks = {"passed": True, "distribution": distribution}

    def commit(self, checks=None):
        with patch.object(stage08_accept, "ROOT", self.root):
            return stage08_accept.commit(self.store, self.cfg, self.condition, self.plan, self.filled,
                                         self.review, checks or self.checks, AcceptingDedup())

    def recovery_runner(self):
        runner = object.__new__(Runner)
        runner.store = self.store
        return runner

    def test_commit_is_idempotent_and_manifest_matches_ledger(self):
        first = self.commit()
        self.commit()
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM accepted").fetchone()[0], 1)
        manifest = read_json(self.store.run_dir / "manifest.json")
        self.assertEqual(manifest["status"], "complete")
        self.assertEqual(manifest["accepted_count"], 1)
        doc = read_json(Path(first["document_path"]))
        self.assertEqual(doc["sentences"][0]["sent_idx"], "fixture_support_001_0")
        self.recovery_runner().recover()

    def test_unreviewed_candidate_cannot_be_committed(self):
        with self.assertRaises(StageFailure) as raised:
            self.commit({"passed": False})
        self.assertEqual(raised.exception.issues[0].code, "UNREVIEWED_COMMIT")
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM accepted").fetchone()[0], 0)
        self.assertFalse((self.root / "output").exists())

    def test_audit_recovers_database_after_interrupted_commit(self):
        self.commit()
        # Simulate the database transaction not having committed while the audit exists.
        self.store.execute("DELETE FROM accepted_relations")
        self.store.execute("DELETE FROM accepted")
        self.store.execute("UPDATE slots SET status='pending',candidate_id=NULL,document_id=NULL")
        self.store.execute("UPDATE candidates SET status='running',finished_at=NULL,final_stage=NULL")
        runner = self.recovery_runner()
        runner.recover()
        runner.recover()
        self.assertEqual(self.store.db.execute("SELECT COUNT(*) FROM accepted").fetchone()[0], 1)
        self.assertEqual(self.store.db.execute("SELECT status FROM candidates").fetchone()[0], "accepted")

    def test_corrupt_accepted_document_is_detected_on_resume(self):
        record = self.commit()
        atomic_json(Path(record["document_path"]), {"changed": True})
        with self.assertRaises(StageFailure) as raised:
            self.recovery_runner().recover()
        self.assertEqual(raised.exception.issues[0].code, "ACCEPTED_DOCUMENT_HASH")


if __name__ == "__main__":
    unittest.main()
