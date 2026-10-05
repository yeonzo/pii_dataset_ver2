"""Korean particles, address formatting and all-occurrence offset rendering."""
from __future__ import annotations

import re

from .common import fail

JOSA_PAIRS = ("은/는", "이/가", "을/를", "과/와", "으로/로", "이다/다", "이며/며", "이고/고", "이라/라", "이란/란", "이나/나", "이든/든", "으로서/로서", "으로써/로써", "으로도/로도", "으로는/로는", "으로만/로만", "과도/와도", "과는/와는", "과의/와의", "과만/와만")
PLACEHOLDER = re.compile(r"<([A-Z][A-Z0-9_]*):(E[0-9]+)>")
REF_PATTERN = re.compile(r"<REF:(C[0-9]+)>")
TOKEN = re.compile(r"<(?:(?P<type>[A-Z][A-Z0-9_]*):(?P<entity>E[0-9]+)|REF:(?P<ref>C[0-9]+))>(?:\{josa:(?P<josa>[^}]+)\})?")
DIGIT_JONG = {"0":21, "1":8, "2":0, "3":16, "4":0, "5":0, "6":1, "7":8, "8":8, "9":0}
LATIN_JONG = {"l":8, "r":8, "m":16, "n":4}
TLD_JONG = {"co.kr":8, "or.kr":8, "ac.kr":8, "go.kr":8, "com":16, "net":19, "org":22, "kr":8, "io":0, "ai":0, "dev":17}
BARE_PARTICLES = sorted({part: pair for pair in JOSA_PAIRS for part in pair.split("/")}.items(), key=lambda x: -len(x[0]))


def jongseong(value: str) -> int:
    stripped = value.strip().lower()
    for tld, jong in sorted(TLD_JONG.items(), key=lambda x: -len(x[0])):
        if stripped.endswith("."+tld):
            return jong
    for ch in reversed(stripped):
        if "가" <= ch <= "힣":
            return (ord(ch)-0xAC00) % 28
        if ch in DIGIT_JONG:
            return DIGIT_JONG[ch]
        if ch.isalpha():
            return LATIN_JONG.get(ch, 0)
    return 0


def choose_josa(value: str, pair: str) -> str:
    if pair not in JOSA_PAIRS:
        fail("JOSA_MARKER", pair, "REPAIR")
    left, right = pair.split("/")
    chars = [ch for ch in value.rstrip() if ch.isalnum()]
    if pair in {"이다/다", "이며/며", "이고/고", "이라/라", "이란/란", "이나/나", "이든/든"} and chars and not ("가" <= chars[-1] <= "힣"):
        return left
    jong = jongseong(value)
    return right if (jong in (0,8) if pair.startswith("으로") else jong == 0) else left


def normalize(text: str) -> str:
    reversed_pairs = {"/".join(reversed(p.split("/"))): p for p in JOSA_PAIRS}
    single_particles = dict(BARE_PARTICLES)
    invariant = {"에", "에서", "에게", "께", "의", "도", "만", "부터", "까지", "보다", "처럼", "마다", "에는", "에서는", "에도"}
    def marker(match):
        x = match.group(1).strip()
        if "/" in x and len(set(x.split("/"))) == 1 and x.split("/")[0] in invariant:
            return x.split("/")[0]
        if x in reversed_pairs:
            return "{josa:"+reversed_pairs[x]+"}"
        if x in invariant:
            return x
        if x in single_particles:
            return "{josa:"+single_particles[x]+"}"
        return match.group(0)
    text = re.sub(r"\{josa:([^}]+)\}", marker, text)
    text = re.sub(r"(>)\s+(?=\{josa:)", r"\1", text)
    for particle, pair in BARE_PARTICLES:
        text = re.sub(r"(<(?:[A-Z][A-Z0-9_]*:E[0-9]+|REF:C[0-9]+)>)"+re.escape(particle)+r"(?=(?:의)?(?:\s|[,.!?;:)]|$))", r"\1{josa:"+pair+"}", text)
    return text


def missing(value) -> bool:
    return value is None or str(value).strip().lower() in {"", "na", "n/a", "null", "none", "nan"}


def address(value, rng) -> str:
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        fail("ADDRESS_SHAPE", "ADDRESS must be a string or object", "REPLAN")
    def join(parts):
        return " ".join(str(p).strip() for p in parts if not missing(p))
    def number(main, sub):
        return str(main).strip() + ("-"+str(sub).strip() if not missing(sub) and str(sub) != "0" else "") if not missing(main) else ""
    sido, sigungu = value.get("sido"), value.get("sigungu")
    road, legal, jibun, detail = [value.get(k) or {} for k in ("road_address", "legal_area", "jibun_address", "detail_address")]
    choices = []
    no = number(road.get("building_main_no"), road.get("building_sub_no"))
    if road.get("road_name") and no:
        choices.append(join([sido, sigungu, road["road_name"], no, detail.get("building_name"), detail.get("detail_text")]))
    no = number(jibun.get("jibun_main_no"), jibun.get("jibun_sub_no"))
    if no:
        area = legal.get("eupmyeondong")
        if area and sigungu and (area == sigungu or str(sigungu).endswith(str(area))):
            area = None
        choices.append(join([sido, sigungu, area, legal.get("ri"), ("산" if jibun.get("is_mountain") else "")+no, detail.get("building_name"), detail.get("detail_text")]))
    if not choices:
        choices.append(join([sido, sigungu, legal.get("eupmyeondong"), detail.get("detail_text")]))
    return rng.choice(choices)


def canonical(value: str, type_: str) -> str:
    if type_ in {"MOBILE_PHONE", "TELEPHONE", "RRN", "BANK_ACCOUNT_NUMBER", "CARD_NUMBER"}:
        return re.sub(r"[^0-9]", "", value)
    return value.strip().lower() if type_ == "EMAIL" else value.strip()


def value_error(type_: str, value: str) -> str | None:
    if missing(value) or len(value) > 120 or re.search(r"[{}\[\]]|\bNone\b", value):
        return "empty or invalid value"
    patterns = {"NAME": r"[가-힣A-Za-z· .'-]{2,60}", "EMAIL": r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", "MOBILE_PHONE": r"[0-9\-()+ ]{9,20}", "TELEPHONE": r"[0-9\-()+ ]{7,20}", "RRN": r"\d{6}-?\d{7}", "CARD_NUMBER": r"[0-9 -]{13,25}", "BANK_ACCOUNT_NUMBER": r"[0-9 -]{8,30}", "AGE": r"\d{1,3}(?:세)?", "DATE_OF_BIRTH": r"\d{4}[-./년 ]\s*\d{1,2}[-./월 ]\s*\d{1,2}(?:일)?", "PASSPORT_NUMBER": r"[A-Za-z0-9]{7,12}", "DRIVER_LICENSE_NUMBER": r"[0-9 -]{10,20}"}
    if type_ in patterns and not re.fullmatch(patterns[type_], value):
        return "value does not match type format"
    return None


def render(draft: dict, plan: dict, values: dict) -> dict:
    entities = {e["entity_id"]: {"entity_id": e["entity_id"], "entity_type": e["entity_type"], "canonical_form": values[e["entity_id"]]["canonical_form"], "mentions": []} for e in plan["entities"]}
    refs = {r["ref_id"]: r for r in draft["refs"]}
    sentences, references = [], []
    total = 0
    for index, seg in enumerate(draft["segments"]):
        text = normalize(seg["text"])
        pieces, offset, cursor = [], 0, 0
        for match in TOKEN.finditer(text):
            prefix = text[cursor:match.start()]
            pieces.append(prefix); offset += len(prefix)
            eid, rid, typ = match.group("entity", "ref", "type")
            if eid:
                if eid not in entities or typ != entities[eid]["entity_type"]:
                    fail("RENDER_ENTITY", f"Invalid placeholder {match.group(0)}", "REPAIR")
                value = values[eid]["value"]
                mention = {"sentence_id": seg["sentence_id"], "sent_idx": index, "form": value, "begin": offset, "end": offset+len(value)}
                entities[eid]["mentions"].append(mention)
            else:
                if rid not in refs:
                    fail("RENDER_REF", rid, "REPAIR")
                value = refs[rid]["surface"]
                references.append({"ref_id": rid, "kind": refs[rid]["kind"], "sentence_id": seg["sentence_id"], "sent_idx": index, "form": value, "begin": offset, "end": offset+len(value)})
            pieces.append(value); offset += len(value)
            if match.group("josa"):
                part = choose_josa(value, match.group("josa")); pieces.append(part); offset += len(part)
            cursor = match.end()
        pieces.append(text[cursor:])
        result = "".join(pieces)
        if re.search(r"<[^>]+>|\{josa:", result):
            fail("RENDER_LEFTOVER_TAG", seg["sentence_id"], "REPAIR")
        sentences.append({"sentence_id": seg["sentence_id"], "sent_idx": index, "section_id": seg["section_id"], "scene_id": seg["scene_id"], "kind": seg["kind"], "sentence": result})
        total += len(result)
    by_index = {s["sent_idx"]: s["sentence"] for s in sentences}
    for mention in [m for e in entities.values() for m in e["mentions"]] + references:
        if by_index[mention["sent_idx"]][mention["begin"]:mention["end"]] != mention["form"]:
            fail("RENDER_SPAN", "Span/form mismatch", "CODE_FIX", True)
    return {"sentences": sentences, "entities": list(entities.values()), "references": references, "rendered_chars": total, "sentence_id_to_index": {s["sentence_id"]: s["sent_idx"] for s in sentences}}
