#!/usr/bin/env python3
"""Export the six accepted JSON documents as human-readable labelled TXT files."""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = Path(__file__).resolve().parent / "readable_txt"

DOCUMENTS = [
    ("support", "고객지원", "refund_request", ROOT / "output/one_support_20261005_v1/dataset/support/one_support_20261005_v1_support_001.json"),
    ("financial", "금융", "fraud_report", ROOT / "output/one_financial_20261005_v1/dataset/financial/one_financial_20261005_v1_financial_001.json"),
    ("medical", "의료", "questionnaire", ROOT / "output/one_medical_questionnaire_20261005_v1/dataset/medical/one_medical_questionnaire_20261005_v1_medical_001.json"),
    ("contract", "계약", "service", ROOT / "output/one_contract_20261005_v1/dataset/contract/one_contract_20261005_v1_contract_001.json"),
    ("legal", "법률", "legal_consultation", ROOT / "output/one_legal_consultation_20261005_v1/dataset/legal/one_legal_consultation_20261005_v1_legal_001.json"),
    ("career_education", "경력·교육", "resume_form", ROOT / "output/one_career_resume_20261005_v1/dataset/career_education/one_career_resume_20261005_v1_career_education_001.json"),
]


def annotate_sentence(text: str, mentions: list[dict]) -> str:
    """Add readable entity markers without changing stored offsets."""
    annotated = text
    for mention in sorted(mentions, key=lambda item: item["begin"], reverse=True):
        begin, end = mention["begin"], mention["end"]
        marker = f"⟦{mention['entity_id']}|{mention['entity_type']}|{text[begin:end]}⟧"
        annotated = annotated[:begin] + marker + annotated[end:]
    return annotated


def render(domain_ko: str, subtype: str, source: Path, data: dict) -> str:
    entity_by_id = {entity["entity_id"]: entity for entity in data["entities"]}
    mentions_by_sentence: dict[str, list[dict]] = {}
    for entity in data["entities"]:
        for mention in entity["mentions"]:
            mentions_by_sentence.setdefault(mention["sent_idx"], []).append(
                {**mention, "entity_id": entity["entity_id"], "entity_type": entity["entity_type"]}
            )

    lines = [
        f"도메인: {domain_ko}",
        f"문서 타입: {subtype}",
        f"원본 JSON: {source}",
        "표기법: ⟦엔티티ID|엔티티타입|본문값⟧",
        "",
        "[본문 + 엔티티 라벨]",
    ]
    for index, sentence in enumerate(data["sentences"]):
        marked = annotate_sentence(
            sentence["sentence"], mentions_by_sentence.get(sentence["sent_idx"], [])
        )
        lines.append(f"[{index:03d}] {marked}")

    lines.extend(["", "[관계 라벨]"])
    for index, relation in enumerate(data["relations"], start=1):
        source_entity = entity_by_id[relation["entity"]]
        target_entity = entity_by_id[relation["target_entity"]]
        lines.append(
            f"R{index} | {relation['privacy_label']} | "
            f"{source_entity['entity_id']}({source_entity['entity_type']}: {source_entity['canonical_form']}) "
            f"--{relation['relation']}--> "
            f"{target_entity['entity_id']}({target_entity['entity_type']}: {target_entity['canonical_form']})"
        )

    lines.extend(["", "[PII 스팬 라벨]"])
    pii_count = 0
    for index, sentence in enumerate(data["sentences"]):
        for span in sentence["PII_set"]:
            pii_count += 1
            lines.append(
                f"S{index:03d} | {span['label']} | [{span['begin']}:{span['end']}] | {span['form']}"
            )
    if pii_count == 0:
        lines.append("없음")

    lines.append("")
    return "\n".join(lines)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    combined = []
    for domain, domain_ko, subtype, source in DOCUMENTS:
        data = json.loads(source.read_text(encoding="utf-8"))
        destination = OUTPUT_DIR / f"{domain}.txt"
        rendered = render(domain_ko, subtype, source, data)
        destination.write_text(rendered, encoding="utf-8")
        combined.append("=" * 100 + "\n" + rendered)
        print(destination)
    combined_path = OUTPUT_DIR / "all_domains.txt"
    combined_path.write_text("\n".join(combined), encoding="utf-8")
    print(combined_path)


if __name__ == "__main__":
    main()
