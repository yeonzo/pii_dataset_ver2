"""Verify domain routing in actual stage requests, without a live provider."""
import random
import unittest

import test_workflow
from relation_pipeline import document_specs as specs
from relation_pipeline.domain_prompts import DOMAIN_PROMPTS, generation_guidance
from relation_pipeline.offline import OfflineClient
from relation_pipeline.stages import stage01_condition as s1, stage02_plan as s2, stage04_draft as s4, stage05_assemble as s5, stage07_review as s7
from relation_pipeline.additions import expand
from relation_pipeline.renderer import render


class Captured(Exception):
    pass


class CaptureClient:
    def request(self, candidate, stage, task, system, payload, schema):
        self.task, self.system, self.payload, self.schema = task, system, payload, schema
        raise Captured()


class DomainPromptTests(unittest.TestCase):
    def setUp(self):
        test_workflow.WorkflowTests.setUp(self)
        self.cfg.update(spec_policy=specs.VERSION, generation_flow='separated_v1', selection={}, relation_count_range=[6,6])

    def condition(self, domain, subtype):
        slot={'slot_id':domain+'_fixture','domain':domain,'subtype':subtype}
        return s1.select_condition(self.cfg,self.store,slot,domain+'_fixture_c1',1)

    def test_all_six_domains_reach_actual_plan_and_both_draft_paths(self):
        cases={'support':'refund_request','career_education':'recommendation','medical':'registration',
               'financial':'fraud_report','legal':'mediation_application','contract':'service'}
        self.assertEqual(set(cases),set(DOMAIN_PROMPTS))
        for domain,subtype in cases.items():
            condition=self.condition(domain,subtype)
            plan=OfflineClient(self.cfg,self.store).plan(condition)
            for stage in ('plan','draft'):
                for policy in ('legacy','prose_v2'):
                    with self.subTest(domain=domain,stage=stage,policy=policy):
                        c={**condition,'document_policy':policy}
                        client=CaptureClient()
                        with self.assertRaises(Captured):
                            if stage=='plan':s2.make_plan(client,c)
                            else:s4.generate(client,c,plan)
                        self.assertIn(DOMAIN_PROMPTS[domain],client.system)
                        for other in set(cases)-{domain}:
                            self.assertNotIn(DOMAIN_PROMPTS[other],client.system)
                        self.assertIn('필수 사실의 구체성',client.system)
                        self.assertEqual(client.task,stage)

    def test_local_repair_and_addition_keep_selected_domain_and_edit_scope(self):
        condition=self.condition('financial','fraud_report')
        offline=OfflineClient(self.cfg,self.store)
        plan=offline.plan(condition);draft=offline.draft(condition,plan,False)
        diagnosis={'issues':[{'code':'LENGTH_SHORTAGE','message':'short','action':'REPAIR'}],
                   'metrics':{'shortage_chars':500,'rendered_chars':1000,
                              'min_chars':condition['min_chars'],'section_shortages':{},'section_chars':{}}}
        for stage in ('repair','expand'):
            client=CaptureClient()
            with self.subTest(stage=stage),self.assertRaises(Captured):
                if stage=='repair':s5.repair(client,draft,condition,plan,diagnosis)
                else:expand(client,draft,condition,plan,{},diagnosis,2)
            self.assertIn(DOMAIN_PROMPTS['financial'],client.system)
            self.assertIn(generation_guidance(condition,stage),client.system)

    def test_every_table_spec_allows_equivalent_prose_without_dropping_facts(self):
        for (domain,subtype),definition in specs.DEFINITIONS.items():
            resolved=specs.resolve(domain,subtype,random.Random(1))
            for section in resolved['sections']:
                if section['mode']!='table':continue
                with self.subTest(subtype=subtype,section=section['section_id']):
                    self.assertIn('문장 나열',section['structure'])
                    self.assertIn('prose',specs.MODES['table'][1])
                    check=next(x for x in resolved['checks'] if x['check_id']==section['section_id'])
                    self.assertTrue(all(f['requirement'] in check['requirement'] for f in section['fact_fields']))

    def test_review_gets_content_policy_but_not_generation_examples(self):
        from test_continuation import fixture
        plan,condition,values,draft=fixture()
        definition=specs.resolve('financial','wire_transfer',random.Random(1))
        condition['document_spec']=definition
        condition['topic']='송금 요청'
        client=CaptureClient()
        filled=render(draft,plan,values)
        with self.assertRaises(Captured):s7.judge(client,filled,plan,condition,draft=draft)
        self.assertIn('문장 나열·목록도 허용된 표현',client.system)
        self.assertIn('누락과 모순은 계속 검수',client.system)
        for prompt in DOMAIN_PROMPTS.values():self.assertNotIn(prompt,client.system)
        self.assertNotIn('document_case',client.payload)

    def test_legacy_conditions_do_not_gain_domain_instructions(self):
        self.assertEqual(generation_guidance({'domain':'financial'},'draft'),'')
