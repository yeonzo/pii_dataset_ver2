"""Serial writer, stage checkpoints and bounded candidate/repair orchestration."""
from __future__ import annotations

import fcntl
import json
from pathlib import Path

from .client import Client
from .common import Issue, StageFailure, atomic_json, digest, fail, file_hash, now, read_json
from .dedup import Dedup
from .statistics import export
from .repair_tasks import build_tasks, evaluate_repair, normalize_sentence_ids
from .coverage import index_final_relations,next_coverage_slot
from .stages import stage01_condition as s1, stage02_plan as s2, stage03_values as s3, stage04_draft as s4, stage05_assemble as s5, stage06_render as s6, stage07_review as s7, stage08_accept as s8


class Runner:
    def __init__(self, store, client=None):
        self.store = store
        self.cfg = read_json(store.run_dir/"run_config.json")
        self._client = client
        self.pool = read_json(Path(self.cfg["pool_path"]))
        self.dedup = Dedup(self.cfg,store)

    @property
    def client(self):
        if self._client is None:
            self._client = Client(self.cfg, self.store)
        if self.cfg.get('generation_flow')=='separated_v1':
            from .call_policy import BoundedClient
            if not isinstance(self._client,BoundedClient):
                self._client=BoundedClient(self._client,self.cfg,self.store)
        return self._client

    def stage(self, candidate: str, number: int, inputs, callback, status_fn=None, name=None, private=False):
        path = self.store.run_dir/"candidates"/candidate/"checkpoints"/(name or f"stage_{number:02d}.json")
        h = digest(inputs)
        if path.exists():
            checkpoint = read_json(path)
            if checkpoint["input_hash"] == h:
                if digest(checkpoint["output"]) != checkpoint["output_hash"]:
                    fail("CHECKPOINT_HASH", str(path), "CODE_FIX", True)
                self.store.event(candidate,number,"checkpoint_reused",{"artifact":str(path),"input_hash":h})
                result = checkpoint["output"]
                reasons = result.get("issues", []) if isinstance(result, dict) else []
                if isinstance(result, dict) and "checks" in result:
                    reasons = result["checks"].get("issues", [])
                metrics = result.get("metrics", {}) if isinstance(result, dict) else {}
                self.store.execute("UPDATE stage_attempts SET status=?,finished_at=?,reasons=?,metrics=? WHERE candidate_id=? AND stage=? AND artifact=? AND status IN ('running','interrupted')",
                                   (checkpoint["status"], now(), json.dumps(reasons, ensure_ascii=False), json.dumps(metrics, ensure_ascii=False), candidate, number, str(path)))
                return checkpoint["output"]
        attempt = self.store.begin_stage(candidate,number,str(path))
        try:
            result = callback()
            status = status_fn(result) if status_fn else "passed"
            reasons = result.get("issues",[]) if isinstance(result,dict) else []
            if isinstance(result,dict) and "checks" in result:
                reasons = result["checks"].get("issues",[])
            metrics = result.get("metrics",{}) if isinstance(result,dict) else {}
            atomic_json(path,{"input_hash":h,"output_hash":digest(result),"output":result,"status":status},private)
            self.store.finish_stage(attempt,status,reasons,metrics,str(path))
            self.store.event(candidate,number,"stage_result",{"status":status,"reasons":reasons,"artifact":str(path)})
            return result
        except StageFailure as exc:
            reasons = [i.json() for i in exc.issues]
            self.store.finish_stage(attempt,"error" if exc.fatal else "failed",reasons,getattr(exc,"metrics",{}))
            self.store.event(candidate,number,"stage_failure",{"fatal":exc.fatal,"reasons":reasons})
            raise
        except BaseException as exc:
            status = "interrupted" if isinstance(exc,(KeyboardInterrupt,SystemExit)) else "error"
            self.store.finish_stage(attempt,status,[Issue("INTERRUPTED" if status=="interrupted" else "IMPLEMENTATION_ERROR",type(exc).__name__,"STOP_RUN").json()])
            raise

    def actions(self, candidate: str) -> int:
        return self.store.db.execute("SELECT COUNT(*) FROM api_calls WHERE candidate_id=? AND task IN ('draft','repair')",(candidate,)).fetchone()[0]

    def recover(self):
        # Crash after audit but before SQLite commit: the audit is the commit marker.
        for path in sorted((self.store.run_dir/"audits").glob("*.json")):
            audit = read_json(path)
            output = Path(audit["document_path"])
            if not output.is_file() or file_hash(output) != audit["document_sha256"]:
                fail("ACCEPTED_DOCUMENT_HASH", str(output), "CODE_FIX", True)
            if self.store.db.execute("SELECT 1 FROM accepted WHERE candidate_id=?",(audit["candidate_id"],)).fetchone():
                continue
            slot = self.store.db.execute("SELECT status FROM slots WHERE slot_id=?",(audit["slot_id"],)).fetchone()
            if not slot or slot[0] == "accepted":
                fail("AUDIT_SLOT_CONFLICT", audit["slot_id"], "CODE_FIX", True)
            with self.store.db:
                self.store.db.execute("INSERT INTO accepted(candidate_id,slot_id,document_id,document_path,document_sha256,plan_fingerprint,structure_fingerprint,normalized_text,metrics,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",tuple(audit[k] if k!="metrics" else json.dumps(audit[k],ensure_ascii=False) for k in ("candidate_id","slot_id","document_id","document_path","document_sha256","plan_fingerprint","structure_fingerprint","normalized_text","metrics","created_at")))
                self.store.db.execute("UPDATE slots SET status='accepted',candidate_id=?,document_id=? WHERE slot_id=?",(audit["candidate_id"],audit["document_id"],audit["slot_id"]))
                self.store.db.execute("UPDATE candidates SET status='accepted',finished_at=?,final_stage=8 WHERE candidate_id=?",(now(),audit["candidate_id"]))
        for row in self.store.rows("SELECT candidate_id,document_sha256 FROM accepted"):
            path = self.store.run_dir/"audits"/(row["candidate_id"]+".json")
            if not path.is_file() or read_json(path)["document_sha256"] != row["document_sha256"]:
                fail("ACCEPTED_AUDIT_MISSING", row["candidate_id"], "CODE_FIX", True)
            if not self.store.rows("SELECT 1 FROM accepted_relations WHERE candidate_id=?",(row["candidate_id"],)):
                audit = read_json(path)
                with self.store.db:
                    index_final_relations(self.store,row["candidate_id"],read_json(Path(audit["document_path"])),row["document_sha256"])
        self.store.manifest()

    def run_candidate(self, slot: dict, candidate: str, ordinal: int, stop_after: int = 8) -> bool:
        current_stage = 1
        try:
            condition = self.stage(candidate,1,{"config_hash":self.cfg["config_hash"],"slot":{k:slot[k] for k in ("slot_id","domain","subtype")},"ordinal":ordinal},lambda:s1.select_condition(self.cfg,self.store,slot,candidate,ordinal))
            separated=self.cfg.get('generation_flow')=='separated_v1'
            if separated:
                condition=dict(condition,generation_flow='separated_v1')
                condition.setdefault('review_evidence_policy',self.cfg['review_evidence_policy'])
            self.store.save_artifact(candidate,"condition.json",condition)
            self.store.execute("UPDATE candidates SET document_format=?,layout_variant=?,topic_id=?,viewpoint=?,condition_json=? WHERE candidate_id=?",(condition["document_format"],condition["layout_variant"],condition["topic_id"],condition["narrative_viewpoint"],json.dumps(condition,ensure_ascii=False),candidate))
            if stop_after == 1:
                return self.pause(candidate,1)
            current_stage = 2
            plan_path = self.store.run_dir/"candidates"/candidate/"plan.json"
            if plan_path.exists():
                plan = read_json(plan_path)
            else:
                feedback = []
                existing_plan = None
                for attempt in range(self.cfg["max_plan_attempts"]):
                    try:
                        def planning():
                            plan = s2.make_plan(self.client,condition,feedback,existing_plan)
                            check = self.dedup.plan_check(plan["plan_fingerprint"],candidate,plan)
                            self.store.save_artifact(candidate,"plan_diversity_check.json",check)
                            # Supply failure is identified before any draft call.
                            try:
                                s3.select_values(plan,condition,self.pool)
                            except StageFailure as exc:
                                exc.plan_attempt = plan
                                raise
                            return plan
                        plan = self.stage(candidate,2,{"condition":condition,"feedback":feedback,"existing_plan":existing_plan},planning,name=f"stage_02_attempt_{attempt+1}.json")
                        self.store.save_artifact(candidate,"plan.json",plan)
                        break
                    except StageFailure as exc:
                        if exc.fatal or attempt+1 == self.cfg["max_plan_attempts"]:
                            raise
                        feedback = [i.json() for i in exc.issues]
                        existing_plan = getattr(exc,"plan_attempt",None)
            if stop_after == 2:
                return self.pause(candidate,2)
            current_stage = 3
            values = self.stage(candidate,3,{"plan":plan,"candidate":candidate},lambda:s3.select_values(plan,condition,self.pool),private=True)
            self.store.save_artifact(candidate,"value_map.json",values,private=True)
            if stop_after == 3:
                return self.pause(candidate,3)
            state_path = self.store.run_dir/"candidates"/candidate/"state.json"
            state = read_json(state_path) if state_path.exists() else {}
            if not state.get("draft"):
                current_stage = 4
                draft = self.stage(candidate,4,{"condition":condition,"plan":plan},lambda:s4.generate(self.client,condition,plan),name="stage_04_initial.json")
                state = {"draft":draft,"revision":1}
                self.store.save_artifact(candidate,"draft_versions/draft_v1.json",draft)
                atomic_json(state_path,state)
            if stop_after == 4:
                return self.pause(candidate,4)
            while True:
                draft = state["draft"]
                current_stage = 5
                def diagnosis():
                    checks,_ = s5.diagnose(draft,condition,plan,values)
                    checks["issues"].extend(state.get("repair_guard_issues",[]))
                    return checks
                diagnosis_result = self.stage(candidate,5,{"draft":draft,"plan":plan,"values":values,"repair_guard_issues":state.get("repair_guard_issues",[])},diagnosis,lambda x:"repair_needed" if x["issues"] else "passed",name=f"stage_05_v{state['revision']}.json")
                self.store.save_artifact(candidate,f"diagnoses/diagnosis_v{state['revision']}.json",diagnosis_result)
                if diagnosis_result["issues"]:
                    if separated:
                        errors=[i for i in diagnosis_result['issues'] if i['code']!='LENGTH_SHORTAGE']
                        if errors:
                            if state.get('local_repairs',0)>=2 or any(i['action'] in ('REPLAN','STOP_CANDIDATE','CODE_FIX') for i in errors):
                                raise StageFailure([Issue(**i) for i in errors])
                            repair_diagnosis={**diagnosis_result,'issues':errors,
                                'metrics':{**diagnosis_result['metrics'],'shortage_chars':0,'section_shortages':{}}}
                            updated=self.repair_document(candidate,state,condition,plan,repair_diagnosis)
                            state={**updated,'local_repairs':state.get('local_repairs',0)+1,'length_additions':state.get('length_additions',0)}
                        else:
                            used=state.get('length_additions',0)
                            if used>=4:
                                raise StageFailure([Issue(**i) for i in diagnosis_result['issues']])
                            state=self.expand_document(candidate,state,condition,plan,values,diagnosis_result,4-used)
                        atomic_json(state_path,state)
                        continue
                    if self.actions(candidate) >= self.cfg["max_document_actions"] or any(i["action"] in ("REPLAN","STOP_CANDIDATE","CODE_FIX") for i in diagnosis_result["issues"]):
                        raise StageFailure([Issue(**i) for i in diagnosis_result["issues"]])
                    state = self.repair_document(candidate,state,condition,plan,diagnosis_result)
                    atomic_json(state_path,state)
                    continue
                assembled = {"draft":diagnosis_result["normalized_draft"],"checks":{k:v for k,v in diagnosis_result.items() if k != "normalized_draft"},"assembled_version":state["revision"]}
                self.store.save_artifact(candidate,"assembled.json",assembled)
                if stop_after == 5:
                    return self.pause(candidate,5)
                current_stage = 6
                def filling():
                    # Keep filled output even when dedup fails, for candidate inspection.
                    from .renderer import render
                    filled = render(assembled["draft"],plan,values)
                    self.store.save_artifact(candidate,"filled.json",filled)
                    filled,diversity = s6.fill_and_check(assembled,condition,plan,values,self.dedup,candidate)
                    return {"filled":filled,"diversity":diversity}
                result = self.stage(candidate,6,{"assembled":assembled,"values":values},filling,name=f"stage_06_v{state['revision']}.json")
                filled = result["filled"]
                self.store.save_artifact(candidate,"diversity_check.json",result["diversity"])
                if stop_after == 6:
                    return self.pause(candidate,6)
                current_stage = 7
                response_feedback = []
                last_review_issues = []
                review_attempts=1 if separated else self.cfg['max_review_response_attempts']
                for review_attempt in range(review_attempts):
                    def reviewing():
                        review = s7.judge(self.client,filled,plan,condition,response_feedback,draft=assembled['draft'])
                        checks = s7.check_review(review,filled,plan,condition,assembled["draft"])
                        version = self.store.db.execute("SELECT COUNT(*)+1 FROM reviews WHERE candidate_id=?",(candidate,)).fetchone()[0]
                        self.store.grade(candidate,version,review,checks["response_valid"],checks["semantic_passed"],checks["format_passed"])
                        self.store.save_artifact(candidate,f"review_versions/review_v{version}.json",{"review":review,"checks":checks,"draft_revision":state["revision"],"reviewed_body_hash":digest(filled),"evidence_sentence_order":{s["sentence_id"]:s["sent_idx"] for s in filled["sentences"]}})
                        return {"review":review,"checks":checks}
                    try:
                        review_result = self.stage(candidate,7,{"review_input":s7.review_input(filled,plan,condition),"feedback":response_feedback},reviewing,lambda x:"passed" if x["checks"]["passed"] else "failed",name=f"stage_07_v{state['revision']}_attempt_{review_attempt+1}.json")
                    except StageFailure as exc:
                        if last_review_issues and any(i.code in {"CANDIDATE_CALL_LIMIT", "RUN_REQUEST_BUDGET", "RUN_COST_BUDGET"} for i in exc.issues):
                            # A request cap can prevent the contract-correction retry.
                            # Retain the actionable findings from the response that
                            # triggered it instead of reporting only the budget limit.
                            previous = [Issue(**i) for i in last_review_issues]
                            combined = previous + exc.issues
                            unique = {(i.code,i.entity_id,i.relation_id,i.sentence_id,i.section_id,i.message):i for i in combined}
                            exc = StageFailure(list(unique.values()),exc.fatal)
                        if exc.issues and all(i.action == "RETRY_RESPONSE" for i in exc.issues):
                            last_review_issues = [i.json() for i in exc.issues]
                        invalid_review = getattr(exc, "review_response", None)
                        if invalid_review is not None:
                            version = self.store.db.execute("SELECT COUNT(*)+1 FROM reviews WHERE candidate_id=?",(candidate,)).fetchone()[0]
                            quality = invalid_review.get("quality", {})
                            if isinstance(quality, dict) and isinstance(quality.get("scores", {}), dict):
                                self.store.grade(candidate,version,invalid_review,False,False,False)
                            self.store.save_artifact(candidate,f"review_versions/invalid_review_v{version}.json",invalid_review)
                        if exc.fatal or any(i.action != "RETRY_RESPONSE" for i in exc.issues) or review_attempt+1 == review_attempts:
                            raise exc
                        response_feedback = [i.json() for i in exc.issues]
                        continue
                    if review_result["checks"]["response_valid"]:
                        break
                    response_feedback = [i for i in review_result["checks"]["issues"] if i["action"] == "RETRY_RESPONSE"]
                    last_review_issues = review_result["checks"]["issues"]
                    if review_attempt+1 == review_attempts:
                        raise StageFailure([Issue(**i) for i in review_result["checks"]["issues"]])
                self.store.save_artifact(candidate,"review.json",review_result)
                if not review_result["checks"]["passed"]:
                    if separated or self.actions(candidate) >= self.cfg["max_document_actions"]:
                        raise StageFailure([Issue(**i) for i in review_result["checks"]["issues"]])
                    semantic_diagnosis = {**diagnosis_result,"issues":review_result["checks"]["issues"]}
                    state = self.repair_document(candidate,state,condition,plan,semantic_diagnosis)
                    atomic_json(state_path,state)
                    continue
                if stop_after == 7:
                    return self.pause(candidate,7)
                current_stage = 8
                self.stage(candidate,8,{"filled":filled,"plan":plan,"review":review_result},lambda:s8.commit(self.store,self.cfg,condition,plan,filled,review_result["review"],review_result["checks"],self.dedup))
                return True
        except StageFailure as exc:
            status = "error" if exc.fatal else "rejected"
            self.store.finish_candidate(candidate,status,current_stage,[i.json() for i in exc.issues])
            self.store.event(candidate,current_stage,"candidate_finished",{"status":status,"reasons":[i.json() for i in exc.issues]})
            if exc.fatal:
                raise
            return False

    def expand_document(self,candidate,state,condition,plan,values,diagnosis,remaining):
        from .additions import expand
        base=diagnosis['normalized_draft']
        result=self.stage(candidate,5,{'base':base,'condition':condition,'plan':plan,'remaining':remaining},
            lambda:expand(self.client,base,condition,plan,values,diagnosis,remaining),
            name=f"expand_v{state['revision']}.json")
        self.store.save_artifact(candidate,f"additions/expansion_v{state['revision']}.json",result)
        revision=state['revision']+1
        self.store.save_artifact(candidate,f'draft_versions/draft_v{revision}.json',result['draft'])
        return {'draft':result['draft'],'revision':revision,'local_repairs':state.get('local_repairs',0),
                'length_additions':state.get('length_additions',0)+1}

    def repair_document(self,candidate: str,state: dict,condition: dict,plan: dict,diagnosis: dict) -> dict:
        base,id_changes = normalize_sentence_ids(diagnosis.get("normalized_draft",state["draft"]))
        values = read_json(self.store.run_dir/"candidates"/candidate/"value_map.json")
        def action():
            tasks = build_tasks(base,condition,plan,diagnosis)
            self.store.save_artifact(candidate,f"repairs/tasks_v{state['revision']}.json",tasks)
            patch = s5.repair(self.client,base,condition,plan,diagnosis,values)
            # Retain even an invalid patch for inspection instead of losing the model response.
            self.store.save_artifact(candidate,f"repairs/repair_v{state['revision']}.json",patch)
            updated = s5.apply_patch(base,patch,diagnosis)
            after,_ = s5.diagnose(updated,condition,plan,values)
            progress,guards = evaluate_repair(base,after["normalized_draft"],plan,diagnosis,after,tasks)
            self.store.event(candidate,5,"repair_evaluated",{"draft_revision":state["revision"],**progress})
            return {"draft":after["normalized_draft"],"patch":patch,"kind":"repair","progress":progress,
                    "repair_guard_issues":guards,"id_repairs":id_changes,"metrics":progress}
        repaired = self.stage(candidate,5,{"base":base,"diagnosis":diagnosis},action,
            lambda x:"passed" if x["progress"]["all_code_checks_passed"] else "repair_needed",name=f"repair_v{state['revision']}.json")
        if "patch" in repaired:
            self.store.save_artifact(candidate,f"repairs/repair_v{state['revision']}.json",repaired["patch"])
        revision = state["revision"]+1
        self.store.save_artifact(candidate,f"repairs/progress_v{state['revision']}.json",repaired["progress"])
        if repaired["id_repairs"]:
            self.store.save_artifact(candidate,f"repairs/id_repairs_v{state['revision']}.json",repaired["id_repairs"])
        self.store.save_artifact(candidate,f"draft_versions/draft_v{revision}.json",repaired["draft"])
        return {"draft":repaired["draft"],"revision":revision,"repair_guard_issues":repaired["repair_guard_issues"]}

    def pause(self,candidate: str,stage: int) -> bool:
        self.store.execute("UPDATE candidates SET status='paused',final_stage=? WHERE candidate_id=?",(stage,candidate))
        return False

    def run(self,max_candidates=None,stop_after=8) -> dict:
        lock_path = self.store.run_dir/"writer.lock"
        with lock_path.open("a") as lock:
            try:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:
                fail("WRITER_BUSY","Another writer owns this run","STOP_RUN",True)
            self.recover()
            completed = 0
            def pending_slots():
                yield from self.store.rows("SELECT * FROM slots WHERE status<>'accepted' ORDER BY slot_id")
                if stop_after == 8:
                    while True:
                        slot = next_coverage_slot(self.store,self.cfg)
                        if slot is None:
                            break
                        yield slot
            for slot in pending_slots():
                while True:
                    if max_candidates is not None and completed >= max_candidates:
                        return export(self.store,self.cfg)
                    previous = self.store.rows("SELECT * FROM candidates WHERE slot_id=? ORDER BY created_at",(slot["slot_id"],))
                    pending = [c for c in previous if c["status"] in ("paused","running","error")]
                    if pending:
                        row = pending[-1]
                        candidate = row["candidate_id"]
                        ordinal = int(candidate.rsplit("_c",1)[1])
                        self.store.execute("UPDATE candidates SET status='running',finished_at=NULL WHERE candidate_id=?",(candidate,))
                    else:
                        if len(previous) >= self.cfg["max_candidates_per_slot"]:
                            self.store.event(None,None,"slot_exhausted",{"slot_id":slot["slot_id"],"attempts":len(previous)})
                            break
                        count = self.store.db.execute("SELECT COUNT(*) FROM candidates WHERE domain=?",(slot["domain"],)).fetchone()[0]
                        if count >= self.cfg["max_candidates_per_domain"]:
                            self.store.event(None,None,"domain_exhausted",{"domain":slot["domain"],"attempts":count})
                            break
                        ordinal = len(previous)+1
                        candidate = slot["slot_id"]+f"_c{ordinal:03d}"
                        self.store.execute("INSERT INTO candidates(candidate_id,slot_id,domain,subtype,created_at) VALUES(?,?,?,?,?)",(candidate,slot["slot_id"],slot["domain"],slot["subtype"],now()))
                    print(f"[{candidate}] {slot['domain']}/{slot['subtype']} 시작",flush=True)
                    try:
                        accepted = self.run_candidate(slot,candidate,ordinal,stop_after)
                    finally:
                        self.store.manifest()
                        export(self.store,self.cfg)
                    completed += 1
                    status = self.store.db.execute("SELECT status FROM candidates WHERE candidate_id=?",(candidate,)).fetchone()[0]
                    print(f"[{candidate}] {status}",flush=True)
                    if accepted or stop_after < 8:
                        break
            return export(self.store,self.cfg)
