"""Execution, frozen-run resume, condition inspection and statistics commands."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from .common import DOMAINS, ROOT, StageFailure, digest, fail, file_hash, load_config, read_json, redact
from .formats import CATALOG, format_for, format_catalog
from .runner import Runner
from .statistics import display, export, snapshot
from .stages.stage00_prepare import prepare, resource_hashes
from .store import Store
from .persons import party_range, role_ids
from .validation import validate_document
from .reference_people import PROFILES as REFERENCE_PROFILES


def run_path(run_id: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_-]+", run_id):
        fail("RUN_ID", "Use only letters, digits, underscore and hyphen", fatal=True)
    return ROOT / "runs" / run_id


def open_run(run_id: str, check_resources: bool = False):
    path = run_path(run_id)
    if not (path / "run_config.json").is_file():
        fail("RUN_NOT_FOUND", str(path), fatal=True)
    cfg = read_json(path / "run_config.json")
    frozen = {k: v for k, v in cfg.items() if k not in {"config_hash", "created_at"}}
    if digest(frozen) != cfg["config_hash"]:
        fail("RUN_CONFIG_HASH", "Frozen run configuration was changed", fatal=True)
    if check_resources and resource_hashes(cfg) != cfg["resource_hashes"]:
        fail("RUN_VERSION_MISMATCH", "Code/resources changed; use a new run ID", fatal=True)
    return Store(path), cfg


def json_print(value):
    print(redact(json.dumps(value, ensure_ascii=False, indent=2)))


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="단계별 관계·privacy 문서 생성과 통계 조회")
    commands = result.add_subparsers(dest="command", required=True)
    catalog = commands.add_parser("catalog", help="도메인·subtype·형식·구성 변형 목록")
    catalog.add_argument("--domain", choices=DOMAINS)
    for name in ("prepare", "run"):
        cmd = commands.add_parser(name, help="조건·slot 준비" if name == "prepare" else "새 실행 준비 및 생성")
        cmd.add_argument("--run-id", required=True)
        cmd.add_argument("--config", type=Path, default=ROOT / "config.json")
        cmd.add_argument("--domain", choices=DOMAINS, action="append")
        cmd.add_argument("--target-per-domain", type=int)
        cmd.add_argument("--subtype")
        cmd.add_argument("--variant")
        cmd.add_argument("--topic")
        cmd.add_argument("--reference-profile", choices=sorted(REFERENCE_PROFILES), help="문서 당사자와 별개인 가상 사례·작품 인물 또는 검증된 공개 약력")
        cmd.add_argument("--viewpoint", choices=("official_record", "staff_record", "party_statement_summary"))
        cmd.add_argument("--offline", action="store_true", help="API 미사용 모의 fixture 실행")
        if name == "run":
            execution_options(cmd)
    resume = commands.add_parser("resume", help="설정·자원·코드가 고정된 실행 재개")
    resume.add_argument("--run-id", required=True)
    execution_options(resume)
    stats = commands.add_parser("stats", help="단계별 수량·등급·탈락 이유·사용량·추정")
    stats.add_argument("--run-id", required=True)
    stats.add_argument("--domain", choices=DOMAINS)
    stats.add_argument("--json", action="store_true")
    stats.add_argument("--export", action="store_true", help="전체 JSON/CSV 통계 다시 내보내기")
    inspect = commands.add_parser("inspect", help="후보의 선택 조건·단계 결과·본문·검수 확인")
    inspect.add_argument("--run-id", required=True)
    inspect.add_argument("--candidate-id", required=True)
    inspect.add_argument("--artifact", default="summary", choices=("summary", "condition", "plan", "values", "draft", "assembled", "filled", "review", "diversity", "history", "prompts"))
    verify = commands.add_parser("validate", help="최종 채택 문서·audit·span·BIO·관계 독립 검증")
    verify.add_argument("--run-id", required=True)
    return result


def execution_options(cmd):
    cmd.add_argument("--max-candidates", type=int, help="이 호출에서 처리할 고유 후보 수")
    cmd.add_argument("--stop-after-stage", type=int, choices=range(1, 9), default=8)


def execute(store, cfg, args):
    if args.max_candidates is not None and args.max_candidates < 1:
        fail("MAX_CANDIDATES", "max_candidates must be positive", fatal=True)
    if cfg["mode"] == "offline":
        from .offline import OfflineClient
        runner = Runner(store, OfflineClient(cfg, store))
    else:
        runner = Runner(store)
    result = runner.run(args.max_candidates, args.stop_after_stage)
    print(display(result))
    print("통계: " + str(store.run_dir / "statistics" / "summary.json"))
    return 0


def main(argv=None) -> int:
    args = parser().parse_args(argv)
    store = None
    try:
        if args.command == "catalog":
            domains = [args.domain] if args.domain else DOMAINS
            json_print({"domains": {domain: [{"subtype": subtype, **info,
                                             "document_format": format_for(domain, subtype)[0],
                                             "fixed_format": format_for(domain, subtype)[1],
                                             "person_count_range":party_range(domain,subtype),
                                             "person_roles":role_ids(domain,subtype),
                                             "layout_variants": format_for(domain, subtype)[2]}
                                            for subtype, info in CATALOG["domains"][domain].items()]
                                     for domain in domains}, "variants": format_catalog()})
            return 0
        if args.command in {"prepare", "run"}:
            cfg = load_config(args.config.resolve())
            selection = {key: getattr(args, key) for key in ("subtype", "variant", "topic", "viewpoint", "reference_profile") if getattr(args, key)}
            store = prepare(cfg, args.run_id, args.domain, args.target_per_domain, selection, "offline" if args.offline else "live")
            cfg = read_json(store.run_dir / "run_config.json")
            if args.command == "prepare":
                json_print({"run_id": args.run_id, "mode": cfg["mode"], "slots": store.rows("SELECT * FROM slots ORDER BY slot_id"),
                            "config": str(store.run_dir / "run_config.json")})
                export(store, cfg)
                return 0
            return execute(store, cfg, args)
        store, cfg = open_run(args.run_id, args.command == "resume")
        if args.command == "resume":
            return execute(store, cfg, args)
        if args.command == "stats":
            if args.export:
                export(store, cfg)
            result = snapshot(store, cfg, args.domain)
            json_print(result) if args.json else print(display(result))
            return 0
        if args.command == "inspect":
            if not re.fullmatch(r"[A-Za-z0-9_-]+", args.candidate_id):
                fail("CANDIDATE_ID", "Invalid candidate ID", fatal=True)
            rows = store.rows("SELECT * FROM candidates WHERE candidate_id=?", (args.candidate_id,))
            if not rows:
                fail("CANDIDATE_NOT_FOUND", args.candidate_id, fatal=True)
            if args.artifact == "summary":
                json_print({"candidate": rows[0], "stages": store.rows("SELECT * FROM stage_attempts WHERE candidate_id=? ORDER BY id", (args.candidate_id,)),
                            "reviews": store.rows("SELECT * FROM reviews WHERE candidate_id=? ORDER BY id", (args.candidate_id,))})
            elif args.artifact == "history":
                json_print(store.rows("SELECT * FROM events WHERE candidate_id=? ORDER BY id", (args.candidate_id,)))
            elif args.artifact == "prompts":
                paths = sorted((store.run_dir / "candidates" / args.candidate_id / "api").glob("request_*.json"))
                json_print({"requests": [read_json(path) for path in paths],
                            "note": "Exact request bodies without authentication headers; historical runs may have no snapshots."})
            else:
                filenames = {"values": "value_map", "draft": "state", "diversity": "diversity_check"}
                path = store.run_dir / "candidates" / args.candidate_id / (filenames.get(args.artifact, args.artifact) + ".json")
                if not path.is_file():
                    fail("ARTIFACT_NOT_READY", str(path), fatal=True)
                json_print(read_json(path))
            return 0
        results = []
        for row in store.rows("SELECT * FROM accepted ORDER BY slot_id"):
            path = Path(row["document_path"])
            audit = store.run_dir / "audits" / (row["candidate_id"] + ".json")
            if not path.is_file() or file_hash(path) != row["document_sha256"] or not audit.is_file():
                fail("ACCEPTED_INTEGRITY", row["candidate_id"], fatal=True)
            if read_json(audit)["document_sha256"] != row["document_sha256"]:
                fail("AUDIT_HASH", row["candidate_id"], fatal=True)
            results.append({"document_id": row["document_id"], **validate_document(read_json(path))})
        json_print({"run_id": args.run_id, "mode": cfg["mode"], "validated": len(results), "documents": results})
        return 0
    except StageFailure as exc:
        print(redact(str(exc)), file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("중단 상태를 기록했습니다. 같은 run ID로 resume할 수 있습니다.", file=sys.stderr)
        return 130
    finally:
        if store is not None:
            store.close()
