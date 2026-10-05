"""All-subtype contracts, public reviewer requirements and unchanged call budgets."""
import contextlib
import copy
import io
import random
import unittest
from unittest.mock import patch

import test_workflow
from test_continuation import fixture,good_review
from relation_pipeline import document_specs as specs
from relation_pipeline.additions import build_request
from relation_pipeline.common import StageFailure,atomic_json,digest,read_json
from relation_pipeline.content_depth import content_depth
from relation_pipeline.coverage import candidate_triples,eligible_targets
from relation_pipeline.formats import CATALOG
from relation_pipeline.offline import OfflineClient
from relation_pipeline.prompt_inputs import condition_input
from relation_pipeline.renderer import render
from relation_pipeline.runner import Runner
from relation_pipeline.schemas import REVIEW,validate
from relation_pipeline.stages import stage01_condition as s1,stage02_plan as s2,stage05_assemble as s5,stage07_review as s7


class DefinitionTests(unittest.TestCase):
    def test_every_active_type_has_five_concrete_dimensions(self):
        self.assertEqual(len(specs.DEFINITIONS),78)
        self.assertEqual(set(d for d,_ in specs.DEFINITIONS),set(CATALOG['domains']))
        for (domain,subtype),definition in specs.DEFINITIONS.items():
            with self.subTest(domain=domain,subtype=subtype):
                self.assertTrue(all(definition[k] for k in ('writer','reader','participant_roles','voice','sections','conditional_rules','completion_criterion')))
                for section in definition['sections']:
                    self.assertIn(section['mode'],specs.MODES)
                    self.assertGreaterEqual(len(section['fact_fields']),2)
                    self.assertTrue(all(f['requirement'].strip() for f in section['fact_fields']))
        self.assertNotIn('resume',CATALOG['domains'])

    def test_subscription_and_goods_resolve_different_content(self):
        a=specs.resolve('support','refund_request',random.Random(1),'구독 해지 후 재청구')
        b=specs.resolve('support','refund_request',random.Random(1),'상품 반품')
        self.assertEqual(a['scenario']['id'],'subscription')
        self.assertEqual(b['scenario']['id'],'goods')
        self.assertNotEqual(a['sections'][2]['fact_fields'],b['sections'][2]['fact_fields'])
        facts=content_depth({'document_spec':a})['facts_to_develop']
        self.assertNotIn('회수 및 검수 상태',facts)
        self.assertTrue(any('제품 회수' in text for text in a['scenario']['exclude']))

    def test_resolution_is_deterministic_and_does_not_mutate_definitions(self):
        before=copy.deepcopy(specs.DEFINITIONS)
        self.assertEqual(specs.resolve('support','refund_request',random.Random(9)),specs.resolve('support','refund_request',random.Random(9)))
        specs.resolve('support','refund_request',random.Random(1),scenario_id='goods')
        self.assertEqual(before,specs.DEFINITIONS)
        with self.assertRaises(StageFailure):specs.resolve('support','refund_request',random.Random(1),scenario_id='not_supported')

    def test_field_contract_rejects_writing_instructions_before_draft(self):
        c={'document_spec':{'version':specs.VERSION}}
        response={'document_case':{'situation':'해지 후 추가 청구가 확인되었다.','scope_decisions':'구독 청구만 확인하고 제품 반품은 제외한다.','end_state':'취소 요청이 접수되어 처리를 기다린다.'},
                  'scene_notes':{'SC1':{'content_facts':{'F1':'피해 금액과 발생 시각을 기재해야 한다.'}}}}
        with self.assertRaises(StageFailure) as caught:specs.check_facts(response,c)
        self.assertEqual(caught.exception.issues[0].code,'SPEC_FACT_NOT_CONCRETE')
        response['scene_notes']['SC1']['content_facts']['F1']='9월 5일 해지 이후 29,000원이 추가 청구되었다.'
        specs.check_facts(response,c)

    def test_review_requires_content_evidence_and_rejects_missing_content(self):
        plan,condition,values,draft=fixture()
        filled=render(draft,plan,values)
        condition['document_spec']={'checks':[{'check_id':'detail','section_id':'main','requirement':'확인된 구체적 사실'}]}
        review=good_review(filled,plan)
        review['spec_checks']={'detail':{'passed':True,'evidence_sentence_ids':['S1'],'reason':'본문에서 확인'}}
        validate(review,specs.review_schema(REVIEW,condition))
        self.assertEqual(specs.check_review_spec(review,condition,filled),([],[]))
        review['spec_checks']['detail']['evidence_sentence_ids']=[]
        self.assertTrue(specs.check_review_spec(review,condition,filled)[0])
        review['spec_checks']['detail'].update(passed=False,reason='실제 금액·일시가 없이 작성 안내만 있다.')
        response,semantic=specs.check_review_spec(review,condition,filled)
        self.assertFalse(response)
        self.assertEqual(semantic[0].code,'DOCUMENT_SPEC_INCOMPLETE')

    def test_heading_or_wrong_section_cannot_support_pass(self):
        condition={'document_spec':{'checks':[{'check_id':'detail','section_id':'main','requirement':'본문'}]}}
        review={'spec_checks':{'detail':{'passed':True,'evidence_sentence_ids':['S1'],'reason':'판정'}}}
        for kind,section in [('heading','main'),('prose','other')]:
            filled={'sentences':[{'sentence_id':'S1','kind':kind,'section_id':section,'sentence':'구체적인 사실과 관련 내역을 작성하는 항목'}]}
            self.assertTrue(specs.check_review_spec(review,condition,filled)[0])

    def test_schema_specialization_does_not_alias_unrelated_fields(self):
        schema=specs.review_schema(REVIEW,{})
        schema['properties']['relation_checks']['items']['properties']['relation_id']['enum']=['R1']
        self.assertNotIn('enum',schema['properties']['quality']['properties']['reason'])
        self.assertNotIn('enum',REVIEW['properties']['relation_checks']['items']['properties']['relation_id'])


class SpecWorkflowTests(unittest.TestCase):
    def setUp(self):
        test_workflow.WorkflowTests.setUp(self)
        self.cfg.update(spec_policy=specs.VERSION,generation_flow='separated_v1')
        self.cfg['config_hash']=digest(self.cfg)
        atomic_json(self.store.run_dir/'run_config.json',self.cfg)

    def test_all_78_conditions_keep_original_length_and_plan_contract(self):
        cfg={**self.cfg,'relation_count_range':[6,6],'selection':{}}
        for domain,subtypes in CATALOG['domains'].items():
            for subtype,info in subtypes.items():
                with self.subTest(domain=domain,subtype=subtype):
                    slot={'slot_id':domain+'_'+subtype,'domain':domain,'subtype':subtype}
                    condition=s1.select_condition(cfg,self.store,slot,slot['slot_id']+'_c1',1)
                    self.assertEqual(condition['min_chars'],max(1500,int(condition['length_target']*.75)))
                    self.assertTrue(info['length_range'][0]<=condition['length_target']<=info['length_range'][1])
                    self.assertEqual(sum(s['target_chars'] for s in condition['section_plan']),condition['length_target'])
                    self.assertEqual(condition['layout_variant'],'type_spec')
                    payload,schema=s2.planning_input(condition)
                    self.assertIn('document_case',schema['properties'])
                    for scene in payload['seed_plan']['scenes']:
                        field=schema['properties']['scene_notes']['properties'][scene['scene_id']]['properties']['content_facts']
                        self.assertGreaterEqual(len(field['properties']),2)
                    self.assertTrue(payload['condition']['document_spec']['completion_criterion'])

    def test_new_spec_runs_with_three_calls_and_audits_checks(self):
        runner=Runner(self.store,OfflineClient(self.cfg,self.store))
        with contextlib.redirect_stdout(io.StringIO()):result=runner.run(max_candidates=1)
        self.assertEqual(result['candidate_status_counts'],{'accepted':1})
        self.assertEqual([r['task'] for r in self.store.rows('SELECT task FROM api_calls ORDER BY id')],['plan','draft','review'])
        root=next((self.store.run_dir/'candidates').iterdir())
        condition=read_json(root/'condition.json')
        plan=read_json(root/'plan.json')
        self.assertIn('document_case',plan)
        draft=read_json(root/'draft_versions/draft_v1.json')
        values=read_json(root/'value_map.json')
        checks,filled=s5.diagnose(draft,condition,plan,values)
        request=s7.review_input(filled,plan,condition)
        self.assertNotIn('role_bindings',request['document_spec'])
        self.assertNotIn('document_case',request)
        self.assertNotIn('context_reason',str(request['relations']))
        self.assertEqual(request['document_spec']['checks'],condition['document_spec']['checks'])
        review=read_json(root/'review.json')
        self.assertTrue(all(c['passed'] for c in review['review']['spec_checks'].values()))
        audit=read_json(next((self.store.run_dir/'audits').glob('*.json')))
        self.assertEqual(audit['document_spec']['checks'],review['review']['spec_checks'])

    def test_addition_receives_section_specific_facts_and_scenario(self):
        slot={'slot_id':'support_fixture','domain':'support','subtype':'refund_request'}
        cfg={**self.cfg,'selection':{'topic':'구독 해지 후 재청구','scenario':'subscription'}}
        condition=s1.select_condition(cfg,self.store,slot,'support_fixture_c1',1)
        plan=OfflineClient(self.cfg,self.store).plan(condition)
        draft=OfflineClient(self.cfg,self.store).draft(condition,plan,False)
        diagnosis={'metrics':{'shortage_chars':500,'rendered_chars':1000,'section_shortages':{'spec_3':500}}}
        request,_,section,_=build_request(draft,condition,plan,diagnosis,2)
        self.assertEqual(section['section_id'],'spec_3')
        self.assertEqual(request['facts_to_develop'],[f['requirement'] for f in section['fact_fields']])
        self.assertEqual(request['document_spec']['scenario']['id'],'subscription')
        self.assertEqual(condition_input(condition)['document_spec'],condition['document_spec'])

    def test_unrelated_guarantee_is_not_sampled_for_service(self):
        slot={'slot_id':'contract_fixture','domain':'contract','subtype':'service'}
        condition=s1.select_condition(self.cfg,self.store,slot,'contract_fixture_c1',1)
        choices=[t for p in ('PII','NON_PII') for t in candidate_triples(condition,p)]
        self.assertFalse(any(t[1] in {'CREDIT_AND_GUARANTEE_RELATION','INSURANCE_RELATION'} for t in choices))

    def test_spec_failure_prevents_acceptance_even_with_high_quality_grades(self):
        class MissingFacts(OfflineClient):
            def request(self,*args):
                result=super().request(*args)
                if args[2]=='review':
                    result['spec_checks']['complete'].update(passed=False,evidence_sentence_ids=[],reason='송금액과 수수료의 실제 내역이 없다.')
                return result
        runner=Runner(self.store,MissingFacts(self.cfg,self.store))
        with contextlib.redirect_stdout(io.StringIO()):result=runner.run(max_candidates=1)
        self.assertEqual(result['candidate_status_counts'],{'rejected':1})
        self.assertIn('DOCUMENT_SPEC_INCOMPLETE',result['final_rejection_reasons'])
        self.assertEqual(len(self.store.rows('SELECT * FROM api_calls')),3)
        self.assertFalse(self.store.rows('SELECT * FROM accepted'))
