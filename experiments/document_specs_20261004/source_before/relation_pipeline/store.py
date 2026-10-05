"""SQLite ledger: attempts, candidates, selections, grades and usage are distinct."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

from .common import atomic_json, now, read_json, redact


class Store:
    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        run_dir.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(run_dir / "statistics.sqlite3", timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
        PRAGMA journal_mode=WAL;
        PRAGMA foreign_keys=ON;
        CREATE TABLE IF NOT EXISTS slots(slot_id TEXT PRIMARY KEY, domain TEXT NOT NULL, subtype TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'pending', candidate_id TEXT, document_id TEXT);
        CREATE TABLE IF NOT EXISTS candidates(candidate_id TEXT PRIMARY KEY, slot_id TEXT NOT NULL REFERENCES slots(slot_id), domain TEXT NOT NULL, subtype TEXT NOT NULL, document_format TEXT, layout_variant TEXT, topic_id TEXT, viewpoint TEXT, status TEXT NOT NULL DEFAULT 'running', created_at TEXT NOT NULL, finished_at TEXT, final_stage INTEGER, reasons TEXT NOT NULL DEFAULT '[]', condition_json TEXT);
        CREATE TABLE IF NOT EXISTS stage_attempts(id INTEGER PRIMARY KEY, candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id), stage INTEGER NOT NULL, attempt INTEGER NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT, reasons TEXT NOT NULL DEFAULT '[]', metrics TEXT NOT NULL DEFAULT '{}', artifact TEXT, UNIQUE(candidate_id,stage,attempt));
        CREATE TABLE IF NOT EXISTS api_calls(id INTEGER PRIMARY KEY, candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id), stage INTEGER NOT NULL, task TEXT NOT NULL, model TEXT NOT NULL, key_slot TEXT NOT NULL, status TEXT NOT NULL, started_at TEXT NOT NULL, finished_at TEXT, input_tokens INTEGER NOT NULL DEFAULT 0, cached_input_tokens INTEGER NOT NULL DEFAULT 0, output_tokens INTEGER NOT NULL DEFAULT 0, estimated_cost_usd REAL NOT NULL DEFAULT 0, error_code TEXT, request_id TEXT);
        CREATE TABLE IF NOT EXISTS reviews(id INTEGER PRIMARY KEY, candidate_id TEXT NOT NULL REFERENCES candidates(candidate_id), version INTEGER NOT NULL, overall TEXT, consistency TEXT, fluency TEXT, suitability TEXT, semantic_passed INTEGER, format_passed INTEGER, response_valid INTEGER NOT NULL, reason TEXT, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS accepted(candidate_id TEXT PRIMARY KEY REFERENCES candidates(candidate_id), slot_id TEXT NOT NULL UNIQUE REFERENCES slots(slot_id), document_id TEXT NOT NULL UNIQUE, document_path TEXT NOT NULL, document_sha256 TEXT NOT NULL, plan_fingerprint TEXT NOT NULL, structure_fingerprint TEXT NOT NULL, normalized_text TEXT NOT NULL, metrics TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY, candidate_id TEXT, stage INTEGER, kind TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS accepted_relations(candidate_id TEXT NOT NULL REFERENCES accepted(candidate_id),relation_id TEXT NOT NULL,relation TEXT NOT NULL,privacy_label TEXT NOT NULL,source TEXT NOT NULL,target TEXT NOT NULL,document_sha256 TEXT NOT NULL,PRIMARY KEY(candidate_id,relation_id));
        CREATE TABLE IF NOT EXISTS coverage_slots(slot_id TEXT PRIMARY KEY REFERENCES slots(slot_id),required_types TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS stage_lookup ON stage_attempts(stage,status);
        CREATE INDEX IF NOT EXISTS candidate_lookup ON candidates(domain,subtype,status);
        """)
        self.db.commit()

    def rows(self, sql: str, params=()) -> list[dict]:
        return [dict(row) for row in self.db.execute(sql, params).fetchall()]

    def execute(self, sql: str, params=()):
        result = self.db.execute(sql, params)
        self.db.commit()
        return result

    def event(self, candidate: str | None, stage: int | None, kind: str, payload: dict):
        self.execute("INSERT INTO events(candidate_id,stage,kind,payload,created_at) VALUES(?,?,?,?,?)", (candidate, stage, kind, redact(json.dumps(payload, ensure_ascii=False)), now()))

    def begin_stage(self, candidate: str, stage: int, artifact=None) -> int:
        attempt = self.db.execute("SELECT COALESCE(MAX(attempt),0)+1 FROM stage_attempts WHERE candidate_id=? AND stage=?", (candidate, stage)).fetchone()[0]
        row = self.execute("INSERT INTO stage_attempts(candidate_id,stage,attempt,status,started_at,artifact) VALUES(?,?,?,'running',?,?)", (candidate, stage, attempt, now(), artifact))
        return row.lastrowid

    def finish_stage(self, attempt_id: int, status: str, reasons=None, metrics=None, artifact=None):
        self.execute("UPDATE stage_attempts SET status=?,finished_at=?,reasons=?,metrics=?,artifact=? WHERE id=?", (status, now(), redact(json.dumps(reasons or [], ensure_ascii=False)), json.dumps(metrics or {}, ensure_ascii=False), artifact, attempt_id))

    def finish_candidate(self, candidate: str, status: str, stage: int, reasons=None):
        self.execute("UPDATE candidates SET status=?,finished_at=?,final_stage=?,reasons=? WHERE candidate_id=?", (status, now(), stage, redact(json.dumps(reasons or [], ensure_ascii=False)), candidate))

    def save_artifact(self, candidate: str, name: str, value, private=False) -> Path:
        path = self.run_dir / "candidates" / candidate / name
        atomic_json(path, value, private)
        return path

    def grade(self, candidate: str, version: int, review: dict, valid: bool, semantic: bool, fmt: bool):
        quality = review.get("quality", {})
        scores = quality.get("scores", {})
        def grade_value(value):
            return value if value in ("상", "중", "하") else None
        self.execute("INSERT INTO reviews(candidate_id,version,overall,consistency,fluency,suitability,semantic_passed,format_passed,response_valid,reason,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", (candidate, version, grade_value(quality.get("overall")), grade_value(scores.get("consistency")), grade_value(scores.get("fluency")), grade_value(scores.get("suitability")), int(semantic), int(fmt), int(valid), redact(quality.get("reason", "")), now()))

    def manifest(self):
        slots = self.rows("SELECT * FROM slots ORDER BY slot_id")
        accepted = self.rows("SELECT candidate_id,slot_id,document_id,document_path,document_sha256 FROM accepted ORDER BY slot_id")
        from .coverage import completion_state
        cfg_path = self.run_dir/"run_config.json"
        cfg = read_json(cfg_path) if cfg_path.exists() else {}
        completion = completion_state(self,cfg)
        complete = completion["complete"]
        atomic_json(self.run_dir / "slots.json", slots)
        atomic_json(self.run_dir / "manifest.json", {"status": "complete" if complete else "incomplete", "updated_at": now(), "accepted_count": len(accepted), "documents": accepted,**completion})

    def close(self):
        self.db.close()
