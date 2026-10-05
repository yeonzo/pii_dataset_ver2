"""Minimal independent relation/privacy review without evidence extraction."""
import copy
import unittest

from test_continuation import fixture
from relation_pipeline.renderer import render
from relation_pipeline.stages.stage07_review import check_review,privacy_only_input


def minimal_review(plan):
    return {
        'relation_checks':[{'relation_id':r['relation_id'],'relation_supported':True,
            'direction_supported':True,'attribution_supported':True,
            'observed_privacy':r['target_privacy'],'reason':'본문에서 관계·방향·귀속을 확인했다.'}
            for r in plan['relations']],
        'unplanned_relations':[],
        'format_adherence':{'document_format_supported':True,'layout_variant_supported':True,
            'viewpoint_supported':True,'section_roles_supported':True,'reason':'형식과 관점이 맞다.'},
        'quality':{'overall':'상','scores':{'consistency':'상','fluency':'상','suitability':'상'},
            'reason':'문서 품질 조건을 충족한다.'},
        'text_issues':[],
    }


class PrivacyOnlyReviewTests(unittest.TestCase):
    def setUp(self):
        self.plan,self.condition,self.values,self.draft=fixture()
        self.condition['relation_review_policy']='privacy_only_v1'
        self.filled=render(self.draft,self.plan,self.values)

    def test_payload_omits_evidence_and_planned_privacy(self):
        payload=privacy_only_input(self.filled,self.plan,self.condition)
        self.assertNotIn('target_privacy',str(payload['relations']))
        self.assertNotIn('relation_evidence',str(payload))
        self.assertNotIn('person_expectation',payload)

    def test_relation_privacy_direction_and_attribution_are_sufficient(self):
        review=minimal_review(self.plan)
        result=check_review(review,self.filled,self.plan,self.condition,self.draft)
        self.assertTrue(result['passed'])
        self.assertTrue(result['response_valid'])
        self.assertTrue(all(x['observed_mode']=='not_collected' for x in result['expression_checks']))

    def test_ambiguous_direction_and_unplanned_relation_fail_semantics(self):
        review=minimal_review(self.plan)
        review['relation_checks'][0].update(relation_supported=False,direction_supported=False,
            attribution_supported=False,observed_privacy='AMBIGUOUS',reason='본문만으로 관계와 귀속을 확정할 수 없다.')
        review['unplanned_relations']=[{'source':'E1','target':'E3','relation':'CONTACT_ASSOCIATION',
            'observed_privacy':'PII','reason':'본문이 개인 연락 관계를 추가로 만든다.'}]
        result=check_review(review,self.filled,self.plan,self.condition,self.draft)
        self.assertTrue(result['response_valid'])
        self.assertFalse(result['semantic_passed'])
        self.assertEqual({i['code'] for i in result['issues']},
            {'RELATION_MEANING','PRIVACY_AMBIGUOUS','UNPLANNED_RELATIONS'})

    def test_unsupported_direction_is_ambiguous_even_if_reviewer_returns_pii(self):
        review=minimal_review(self.plan)
        review['relation_checks'][0].update(direction_supported=False,observed_privacy='PII',
            reason='관계는 보이지만 어느 당사자에게 귀속되는지 확정할 수 없다.')
        result=check_review(review,self.filled,self.plan,self.condition,self.draft)
        codes={i['code'] for i in result['issues']}
        self.assertEqual(codes,{'RELATION_MEANING','PRIVACY_AMBIGUOUS'})


if __name__=='__main__':
    unittest.main()
