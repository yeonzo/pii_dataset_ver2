"""Budget, merge safety and production routing for the separated flow."""
import contextlib
import io
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import test_workflow
from test_continuation import fixture
from relation_pipeline.additions import merge_response
from relation_pipeline.call_policy import BoundedClient
from relation_pipeline.common import Issue, StageFailure, atomic_json, digest, read_json
from relation_pipeline.offline import OfflineClient
from relation_pipeline.runner import Runner
from relation_pipeline.stages.stage05_assemble import diagnose


class BudgetTests(unittest.TestCase):
    def setUp(self):
        root=tempfile.TemporaryDirectory()
        self.addCleanup(root.cleanup)
        self.store=SimpleNamespace(run_dir=Path(root.name),event=lambda *args:None)
        self.calls=[]
        self.fail_tasks=set()
        def request(*args):
            self.calls.append(args[2])
            if args[2] in self.fail_tasks:
                self.fail_tasks.remove(args[2])
                raise StageFailure([Issue('BAD_RESPONSE','retry me','RETRY_RESPONSE')])
            return {'ok':True}
        self.inner=SimpleNamespace(request=request)
        self.cfg={'max_provider_requests_per_candidate':7}
        self.client=BoundedClient(self.inner,self.cfg,self.store)

    def call(self,task,number=1):
        return self.client.request('sample',5,task,'system',{'number':number},{})

    def test_six_operations_and_one_retry_are_seven_calls(self):
        self.fail_tasks.add('draft')
        for task,number in [('plan',1),('draft',1),('repair',1),('expand',1),('expand',2),('review',1)]:
            self.call(task,number)
        state=self.client.state('sample')[1]
        self.assertEqual((state['requests'],state['retries']),(7,1))
        self.assertEqual(len(self.calls),7)
        with self.assertRaises(StageFailure):self.call('expand',3)
        self.assertEqual(len(self.calls),7)

    def test_retry_is_shared_across_tasks(self):
        self.fail_tasks.update(['expand','review'])
        self.call('expand')
        with self.assertRaises(StageFailure):self.call('review')
        self.assertEqual(self.calls,['expand','expand','review'])
        self.assertEqual(self.client.state('sample')[1]['retries'],1)

    def test_resume_returns_validated_cache_without_call(self):
        self.call('expand')
        self.client=BoundedClient(self.inner,self.cfg,self.store)
        self.call('expand')
        self.assertEqual(self.calls,['expand'])

    def test_replayed_draft_cap_is_five_including_retry(self):
        self.cfg['max_provider_requests_per_candidate']=5
        self.fail_tasks.add('repair')
        for task,number in [('repair',1),('expand',1),('expand',2),('review',1)]:self.call(task,number)
        with self.assertRaises(StageFailure):self.call('draft')
        self.assertEqual(len(self.calls),5)

    def test_post_response_validator_consumes_same_retry(self):
        seen=[]
        def validator(response):
            seen.append(response)
            if len(seen)==1:raise StageFailure([Issue('REPEATED','bad addition','RETRY_RESPONSE')])
            return {'validated':True}
        result=self.client.validated_request('sample',5,'expand','system',{}, {},validator)
        self.assertEqual(result,{'validated':True})
        self.assertEqual(self.calls,['expand','expand'])


class AdditionTests(unittest.TestCase):
    def setUp(self):
        self.plan,self.condition,self.values,self.draft=fixture()
        self.condition.update(min_chars=1500,length_target=2000)
        self.condition['section_plan'][0]['target_chars']=2000
        self.checks,_=diagnose(self.draft,self.condition,self.plan,self.values)
        self.draft=self.checks['normalized_draft']
        self.sentences=[
            '오류를 재현할 때에는 저장 버튼을 누른 직후와 화면을 다시 불러온 뒤의 상태를 각각 비교했고, 새로 입력한 설정이 다음 화면에 반영되지 않는 현상만 확인되어 조회 기능의 장애와 구분했다.',
            '처리 담당자는 기존 설정을 먼저 보관한 다음 임시 설정으로 같은 작업을 수행했으며, 임시 설정에서는 정상적으로 저장되는 점을 근거로 기존 설정의 변환 과정부터 추가 점검하기로 했다.']

    def merge(self,sentences):
        return merge_response({'section_id':'main','sentences':sentences},self.draft,self.condition,
                              self.plan,self.values,self.checks,self.condition['section_plan'][0],self.plan['scenes'][0],200)

    def test_merge_preserves_every_original_and_evidence(self):
        original=deepcopy(self.draft)
        result=self.merge(self.sentences)
        ids={s['sentence_id'] for s in original['segments']}
        self.assertEqual([s for s in result['draft']['segments'] if s['sentence_id'] in ids],original['segments'])
        self.assertEqual(result['draft']['relation_evidence'],original['relation_evidence'])
        self.assertEqual(result['draft']['refs'],original['refs'])
        self.assertEqual(self.draft,original)

    def test_bad_additions_never_change_original(self):
        for sentences,code in [([self.sentences[0]]*2,'ADDITION_REPEAT'),
                               (['',self.sentences[1]],'ADDITION_TEXT'),
                               (['새 연락처는 010-1234-5678이다.',self.sentences[1]],'ADDITION_IDENTIFIER'),
                               (['<NAME:E1>에게 알렸다.',self.sentences[1]],'ADDITION_IDENTIFIER'),
                               (['확인했다.\n완료했다.',self.sentences[1]],'ADDITION_TEXT')]:
            with self.subTest(code=code):
                original=deepcopy(self.draft)
                with self.assertRaises(StageFailure) as caught:self.merge(sentences)
                self.assertEqual(caught.exception.issues[0].code,code)
                self.assertEqual(self.draft,original)

    def test_explicit_numeric_conflict_rejected(self):
        self.draft['segments'][-1]['text']='처리 기간: 3일'
        with self.assertRaises(StageFailure) as caught:self.merge(['처리 기간: 5일',self.sentences[1]])
        self.assertEqual(caught.exception.issues[0].code,'ADDITION_FACT_CONFLICT')

    def test_local_repair_disallows_fragment_output_and_length_work(self):
        from relation_pipeline.repair_tasks import build_tasks,repair_contract
        self.condition['generation_flow']='separated_v1'
        diagnosis={**self.checks,'issues':[Issue('RELATION_MEANING','wrong direction','REWRITE_SCENE',relation_id='R1').json()],
                   'metrics':{**self.checks['metrics'],'shortage_chars':0,'section_shortages':{}}}
        tasks=build_tasks(self.draft,self.condition,self.plan,diagnosis)
        schema=repair_contract(self.draft,self.condition,self.plan,tasks)
        self.assertEqual(tasks['length_mode'],'targeted_repair_only')
        self.assertEqual(schema['properties']['continuations']['properties'],{})
        forms=[v['properties']['form']['enum'][0] for v in schema['properties']['relation_repairs']['properties']['R1']['anyOf']]
        self.assertEqual(forms,['sentence','linked_text'])


class SeparatedWorkflowTests(unittest.TestCase):
    def setUp(self):
        test_workflow.WorkflowTests.setUp(self)
        self.cfg['generation_flow']='separated_v1'
        self.cfg['config_hash']=digest(self.cfg)
        atomic_json(self.store.run_dir/'run_config.json',self.cfg)

    def run_case(self,scenario='normal',stop_after=8):
        runner=Runner(self.store,OfflineClient(self.cfg,self.store,scenario))
        with contextlib.redirect_stdout(io.StringIO()):
            result=runner.run(max_candidates=1,stop_after=stop_after)
        tasks=[r['task'] for r in self.store.rows('SELECT task FROM api_calls ORDER BY id')]
        return result,tasks

    def test_normal_document_uses_three_calls_and_fact_plan(self):
        result,tasks=self.run_case()
        self.assertEqual(result['candidate_status_counts'],{'accepted':1})
        self.assertEqual(tasks,['plan','draft','review'])
        request=next((self.store.run_dir/'candidates').glob('*/api/request_00001.json'))
        wire=read_json(request)['body']['text']['format']['schema']
        self.assertTrue(all('facts' in v['properties'] for v in wire['properties']['scene_notes']['properties'].values()))

    def test_short_document_uses_only_additions_before_review(self):
        result,tasks=self.run_case('short_then_repair')
        self.assertEqual(result['candidate_status_counts'],{'accepted':1})
        self.assertNotIn('repair',tasks)
        self.assertIn('expand',tasks)
        self.assertLessEqual(tasks.count('expand'),2)
        self.assertEqual(tasks[-1],'review')
        audits=list((self.store.run_dir/'candidates').glob('*/additions/*.json'))
        self.assertTrue(audits)
        self.assertTrue(all(read_json(p)['original_segments_unchanged'] for p in audits))

    def test_failed_semantics_do_not_trigger_repair_and_rereview(self):
        result,tasks=self.run_case('review_privacy_failure')
        self.assertEqual(result['candidate_status_counts'],{'rejected':1})
        self.assertEqual(tasks,['plan','draft','review'])

    def test_invalid_review_retries_once_and_preserves_grades(self):
        result,tasks=self.run_case('review_schema_then_retry')
        self.assertEqual(result['candidate_status_counts'],{'accepted':1})
        self.assertEqual(tasks,['plan','draft','review','review'])
        self.assertEqual([r['response_valid'] for r in self.store.rows('SELECT response_valid FROM reviews ORDER BY id')],[0,1])

    def test_resume_does_not_repeat_planning(self):
        result,_=self.run_case(stop_after=3)
        self.assertEqual(result['candidate_status_counts'],{'paused':1})
        result,tasks=self.run_case()
        self.assertEqual(result['candidate_status_counts'],{'accepted':1})
        self.assertEqual(tasks,['plan','draft','review'])

    def test_old_condition_inherits_sentence_id_review_policy(self):
        from relation_pipeline.stages import stage01_condition
        select=stage01_condition.select_condition
        def old_condition(*args):
            condition=select(*args)
            condition.pop('review_evidence_policy',None)
            condition.pop('generation_flow',None)
            return condition
        with patch.object(stage01_condition,'select_condition',side_effect=old_condition):
            result,_=self.run_case()
        self.assertEqual(result['candidate_status_counts'],{'accepted':1})
        condition=read_json(next((self.store.run_dir/'candidates').glob('*/condition.json')))
        self.assertEqual(condition['review_evidence_policy'],'sentence_ids')

    def test_resume_after_addition_checkpoint_reuses_response(self):
        original=Runner.expand_document
        interrupted=[False]
        def crash_after_checkpoint(runner,*args):
            result=original(runner,*args)
            if not interrupted[0]:
                interrupted[0]=True
                raise KeyboardInterrupt()
            return result
        with patch.object(Runner,'expand_document',new=crash_after_checkpoint):
            with self.assertRaises(KeyboardInterrupt):self.run_case('short_then_repair')
        before=len(self.store.rows("SELECT * FROM api_calls WHERE task='expand'"))
        result,tasks=self.run_case('short_then_repair')
        self.assertEqual(result['candidate_status_counts'],{'accepted':1})
        self.assertLessEqual(tasks.count('expand'),2)
        self.assertEqual(before,1)
