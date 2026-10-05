"""Export the executable registry as readable domain documents and JSON."""
from pathlib import Path
from relation_pipeline.common import ROOT,atomic_json
from relation_pipeline.document_specs import DEFINITIONS,DOMAIN_GUIDANCE,SCENARIOS,UPSTREAM,VERSION,RELATION_TYPES
from relation_pipeline.formats import CATALOG
from relation_pipeline.domain_prompts import DOMAIN_PROMPTS,CONTENT_GUIDANCE,VERSION as PROMPT_VERSION


def export(root=ROOT):
    directory=root/'docs/document_specs'
    directory.mkdir(parents=True,exist_ok=True)
    index=['# 타입별 문서 작성 계약', '',
           f'정의 버전: `{VERSION}`. 원본 Git 기준: `{UPSTREAM}`.', '',
           '실행 정의는 `relation_pipeline/spec_definitions.py`, 상황 선택·프롬프트·검수 연결은 `relation_pipeline/document_specs.py`에 있다. 이 문서는 실행 정의에서 자동 생성했다.', '',
           '공통 규칙 → 도메인 지침 → subtype 전용 항목·화자 → 선택 상황 → 항목별 확정 사실 순서로 요청을 구성한다. 필수 사실은 계획의 `content_facts`에 채우고, 독립 검수는 실제 본문의 근거 문장으로 `spec_checks`를 판정한다.', '',
           '[도메인별 생성 프롬프트 전문](DOMAIN_PROMPTS.md)은 작성 맥락·타입별 전개 순서·세부 사실·서술 예시·일관성 확인으로 구성한다. 문장 나열과 목록을 허용하며 표 모양이 아닌 실제 필수 내용으로 검수한다.', '',
           '분량은 원본 subtype 범위와 `max(1500, int(length_target * .75))` 하한을 유지하며 전체 상한은 두지 않는다. 부족한 분량은 원문을 보존한 추가 방식으로 처리한다. 새로운 LLM 호출 단계는 추가하지 않는다.', '',
           '각 정의는 합성 문서의 작성·평가 기준이다. 아래 내용이 실제 법률·의료·금융 서식의 적법성이나 임상적 타당성을 보증하지 않는다.', '',
           '| 도메인 | 타입 수 | 전체 정의 |','| --- | ---: | --- |']
    domains={}
    for domain,subtypes in CATALOG['domains'].items():
        index.append(f'| {domain} | {len(subtypes)} | [{domain}.md](docs/document_specs/{domain}.md) |')
        lines=[f'# {domain} — {len(subtypes)}개 타입', '',DOMAIN_GUIDANCE[domain], '']
        domains[domain]={}
        for subtype in subtypes:
            p=DEFINITIONS[domain,subtype]
            domains[domain][subtype]={**p,'compatible_relation_types':sorted(RELATION_TYPES[subtype])}
            lines += [f'## {subtype} — {p["label"]}', '',
                f'- 작성자: {p["writer"]}',f'- 독자: {p["reader"]}',f'- 작성 관점: `{p["voice"]}`',
                '- 당사자 역할: '+' / '.join(p['participant_roles']), '',
                '| 순서 | 실제 항목명 | 표현 형식 | 반드시 채울 사실 |',
                '| ---: | --- | --- | --- |']
            for i,s in enumerate(p['sections'],1):
                lines.append(f'| {i} | {s["title"]} | {s["structure"]} | '+ ' / '.join(f['requirement'] for f in s['fact_fields'])+' |')
            lines += ['', '**상황별 포함·제외:** '+p['conditional_rules'][0], '', '**완성 기준:** '+p['completion_criterion'], '']
            if subtype in SCENARIOS:
                lines += ['| 선택 상황 ID | 상황 | 포함 | 제외 |','| --- | --- | --- | --- |']
                for key,label,keywords,include,exclude in SCENARIOS[subtype]:
                    lines.append(f'| `{key}` | {label} | '+ ' / '.join(include)+' | '+' / '.join(exclude)+' |')
                lines.append('')
        (directory/(domain+'.md')).write_text('\n'.join(lines)+'\n',encoding='utf-8')
    index += ['', '## 적용 경로', '',
              '1. 조건 선정: 타입별 작성자·독자·역할·전용 항목을 고정하고 상황을 선택한다. 명시적인 `--topic`은 유지하며 `--scenario`로 지원되는 상황을 지정할 수 있다.',
              '2. 계획: 하나의 사건과 조건별 적용 여부·종료 상태를 확정하고 항목마다 필수 사실을 채운다. 작성 지시만 들어간 사실은 초안 생성 전에 거부한다.',
              '3. 초안·국소 수정: 동일한 정의와 확정 사실을 사용한다. 원문 전체 재생성 없이 오류 부분만 수정한다.',
              '4. 분량 추가: 선택한 항목의 필수 사실과 확정 상황 안에서 새 내용만 추가한다.',
              '5. 독립 검수: 생성자의 사실 계획·정답 역할 연결은 제공하지 않는다. 공통 작성 요구와 본문만으로 각 완성 기준을 확인하고 실제 근거 문장 ID를 남긴다. 제목만 있거나 정보가 빠졌으면 탈락한다.', '',
              '## 실행', '', '```bash',
              'python -m relation_pipeline catalog --specs --domain medical',
              'python -m relation_pipeline run --run-id specs_NEW_ID --domain support --subtype refund_request --scenario subscription --max-candidates 1 --target-per-domain 1',
              '```', '',
              '기본 설정은 `spec_policy: type_specs_v1`이다. 전용 형식의 variant는 `type_spec`이며 기존 범용 variant를 지정하려면 별도 설정의 `spec_policy: legacy`를 사용한다. 이전 run에 이 키가 없으면 기존 경로를 유지한다. `resume` 도메인은 포함하지 않는다.', '',
              '재생성: `python -m experiments.export_document_specs`. 전체 기계 판독 정의: [catalog.json](docs/document_specs/catalog.json).']
    (root/'DOCUMENT_SPECS.md').write_text('\n'.join(index)+'\n',encoding='utf-8')
    atomic_json(directory/'catalog.json',{'version':VERSION,'upstream_commit':UPSTREAM,'domains':domains,'scenarios':SCENARIOS})
    prompts=['# 도메인별 생성 프롬프트', '',f'버전: `{PROMPT_VERSION}`. 실행 소스: `relation_pipeline/domain_prompts.py`.', '',
        '6개 도메인 모두 같은 다섯 구획으로 구성하되, 각 도메인의 업무 사실과 판단 기준을 별도로 정의한다. 78개 subtype의 전용 필드와 함께 계획·초안·국소 수정·분량 추가에 전달한다. 실제 호출에는 선택한 도메인 하나만 들어간다.', '',
        '문장 나열·목록·표는 모두 허용한다. 필수 사실의 누락·모순과 역할 오류는 계속 검수하며, 문장 나열 또는 표 헤더 부재 자체는 탈락 사유가 아니다. 분량 기준과 호출 상한은 그대로다.', '',
        '## 공통 구체성 지침', '',CONTENT_GUIDANCE.strip(), '']
    for domain,prompt in DOMAIN_PROMPTS.items():
        prompts += ['## '+domain, '']
        for line in prompt.strip().splitlines():
            if line.startswith('[') and line.endswith(']'):
                prompts += ['', '### '+line[1:-1].split(' / ',1)[-1], '']
            else:
                prompts += [line, '']
    (root/'DOMAIN_PROMPTS.md').write_text('\n'.join(prompts)+'\n',encoding='utf-8')
    return directory


if __name__=='__main__':print(export())
