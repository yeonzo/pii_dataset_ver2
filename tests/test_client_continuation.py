from __future__ import annotations

import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from relation_pipeline.client import Client
from relation_pipeline.common import StageFailure, load_config, now, read_json
from relation_pipeline.schemas import BOOL, obj
from relation_pipeline.store import Store


class ClientContinuationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.store = Store(Path(directory.name))
        self.addCleanup(self.store.close)
        self.store.execute("INSERT INTO slots(slot_id,domain,subtype) VALUES('S1','support','support_ticket')")
        self.store.execute("INSERT INTO candidates(candidate_id,slot_id,domain,subtype,created_at) VALUES(?,?,?,?,?)",
                           ("C1", "S1", "support", "support_ticket", now()))
        self.cfg = load_config()
        self.cfg['generation_flow'] = 'legacy'  # Legacy transport owns its retry; new flow shares it.
        self.keys = [("OPENAI_API_KEY_1", "unit-test-key-1"), ("OPENAI_API_KEY_2", "unit-test-key-2")]
        with patch("relation_pipeline.client.load_keys", return_value=self.keys):
            self.client = Client(self.cfg, self.store)

    def response(self):
        return io.BytesIO(json.dumps({"id": "fixture-response", "status": "completed",
                                      "usage": {"input_tokens": 10, "output_tokens": 5,
                                                "input_tokens_details": {"cached_tokens": 2}},
                                      "output": [{"content": [{"type": "output_text", "text": '{"ok":true}'}]}]}).encode())

    def request(self, task="plan"):
        return self.client.request("C1", 7 if task == "review" else 2, task, "Return JSON", {"fixture": True}, obj(ok=BOOL))

    def test_model_routing_and_key_rotation_use_distinct_request_formats(self):
        bodies, authorizations = [], []
        def respond(request, timeout):
            bodies.append(json.loads(request.data))
            authorizations.append(request.get_header("Authorization"))
            return self.response()
        with patch("relation_pipeline.client.urllib.request.urlopen", side_effect=respond):
            self.assertEqual(self.request(), {"ok": True})
            self.assertEqual(self.request("review"), {"ok": True})
        self.assertEqual([b["model"] for b in bodies], ["gpt-4o-mini", "gpt-5-mini"])
        self.assertEqual(bodies[0]["temperature"], 0.7)
        self.assertNotIn("temperature", bodies[1])
        self.assertEqual(bodies[1]["reasoning"], {"effort": "low"})
        self.assertTrue(all(b["text"]["format"]["strict"] for b in bodies))
        self.assertNotEqual(authorizations[0], authorizations[1])
        self.assertEqual([c["key_slot"] for c in self.store.rows("SELECT * FROM api_calls ORDER BY id")],
                         ["OPENAI_API_KEY_1", "OPENAI_API_KEY_2"])
        snapshots = [read_json(path) for path in sorted((self.store.run_dir / "candidates/C1/api").glob("request_*.json"))]
        self.assertEqual([s["body"] for s in snapshots], bodies)
        encoded = json.dumps(snapshots)
        self.assertNotIn("Authorization", encoded)
        self.assertTrue(all(key not in encoded for _,key in self.keys))

    def test_transient_retry_counts_both_calls_and_rotates_key(self):
        transient = urllib.error.HTTPError("https://example.invalid", 429, "limited", {},
                                           io.BytesIO(b'{"error":{"code":"rate_limit_exceeded","message":"limited"}}'))
        with patch("relation_pipeline.client.time.sleep"), patch("relation_pipeline.client.urllib.request.urlopen",
                                                                 side_effect=[transient, self.response()]):
            self.assertEqual(self.request(), {"ok": True})
        rows = self.store.rows("SELECT * FROM api_calls ORDER BY id")
        self.assertEqual([c["status"] for c in rows], ["error", "completed"])
        self.assertEqual([c["key_slot"] for c in rows], ["OPENAI_API_KEY_1", "OPENAI_API_KEY_2"])

    def test_request_cap_blocks_network_before_exceeding_budget(self):
        self.cfg["max_provider_requests_per_candidate"] = 1
        with patch("relation_pipeline.client.urllib.request.urlopen", side_effect=lambda *a, **k: self.response()) as transport:
            self.request()
            with self.assertRaises(StageFailure) as raised:
                self.request("review")
        self.assertEqual(transport.call_count, 1)
        self.assertEqual(raised.exception.issues[0].code, "CANDIDATE_CALL_LIMIT")

    def test_separated_transport_has_no_hidden_retry(self):
        from relation_pipeline.call_policy import BoundedClient
        self.cfg['generation_flow']='separated_v1'
        transient=urllib.error.URLError('temporary connection failure')
        bounded=BoundedClient(self.client,self.cfg,self.store)
        with patch('relation_pipeline.client.urllib.request.urlopen',side_effect=[transient,self.response()]) as transport:
            result=bounded.request('C1',2,'plan','Return JSON',{'fixture':True},obj(ok=BOOL))
        self.assertEqual(result,{'ok':True})
        self.assertEqual(transport.call_count,2)
        self.assertEqual(bounded.state('C1')[1]['retries'],1)
        self.assertEqual(len(self.store.rows('SELECT * FROM api_calls')),2)

    def test_cost_reservation_blocks_network_before_request(self):
        self.cfg["run_cost_budget_usd"] = 0.000001
        with patch("relation_pipeline.client.urllib.request.urlopen") as transport:
            with self.assertRaises(StageFailure) as raised:
                self.request()
        transport.assert_not_called()
        self.assertTrue(raised.exception.fatal)
        self.assertEqual(raised.exception.issues[0].code, "RUN_COST_BUDGET")

    def test_provider_error_redacts_key_in_rejection_and_event_log(self):
        error = urllib.error.HTTPError("https://example.invalid", 401, "invalid", {},
                                       io.BytesIO(b'{"error":{"code":"invalid_api_key","message":"invalid sk-test-secret"}}'))
        with patch("relation_pipeline.client.urllib.request.urlopen", side_effect=error):
            with self.assertRaises(StageFailure) as raised:
                self.request()
        self.assertNotIn("sk-test-secret", str(raised.exception))
        self.assertNotIn("sk-test-secret", json.dumps(self.store.rows("SELECT * FROM events")))


if __name__ == "__main__":
    unittest.main()
