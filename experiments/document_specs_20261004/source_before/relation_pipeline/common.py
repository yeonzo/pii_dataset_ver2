from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DOMAINS = ("career_education", "contract", "financial", "legal", "medical", "support")
TYPES = ("NAME", "ADDRESS", "WORKPLACE", "DEPARTMENT", "POSITION", "SCHOOL", "MAJOR", "AGE", "DATE_OF_BIRTH", "MOBILE_PHONE", "TELEPHONE", "PASSPORT_NUMBER", "RRN", "DRIVER_LICENSE_NUMBER", "VEHICLE_NUMBER", "BANK_ACCOUNT_NUMBER", "CARD_NUMBER", "EMAIL")
STAGES = {0: "prepare", 1: "condition", 2: "plan", 3: "values", 4: "draft", 5: "assemble", 6: "render_dedup", 7: "review", 8: "accept"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def atomic_json(path: Path, value: Any, private: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".pending-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(name, 0o600 if private else 0o644)
        os.replace(name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def redact(text: Any) -> str:
    return re.sub(r"sk-[A-Za-z0-9_-]+", "[REDACTED_API_KEY]", str(text))


@dataclass
class Issue:
    code: str
    message: str
    action: str = "REPAIR"
    entity_id: str = ""
    relation_id: str = ""
    sentence_id: str = ""
    section_id: str = ""

    def json(self) -> dict:
        return vars(self).copy()


class StageFailure(Exception):
    def __init__(self, issues: list[Issue], fatal: bool = False):
        self.issues = issues
        self.fatal = fatal
        super().__init__("; ".join(i.code + ": " + i.message for i in issues))


def fail(code: str, message: str, action: str = "REPLAN", fatal: bool = False):
    raise StageFailure([Issue(code, message, action)], fatal)


def load_config(path: Path = ROOT / "config.json") -> dict:
    cfg = read_json(path)
    for key in ("pool_path", "reference_dataset"):
        if cfg.get(key):
            cfg[key] = str((path.parent / cfg[key]).resolve())
    return cfg


def load_keys() -> list[tuple[str, str]]:
    values = {}
    env_file = ROOT / ".env"
    if env_file.exists():
        if env_file.stat().st_mode & 0o077:
            fail("KEY_FILE_PERMISSIONS", ".env must be mode 600", fatal=True)
        for line in env_file.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                values[key.strip()] = value.strip().strip("\"'")
    return [(name, os.environ.get(name) or values[name]) for name in ("OPENAI_API_KEY_1", "OPENAI_API_KEY_2", "OPENAI_API_KEY") if os.environ.get(name) or values.get(name)]
