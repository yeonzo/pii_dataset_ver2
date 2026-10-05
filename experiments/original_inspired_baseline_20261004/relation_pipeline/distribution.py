"""Count actual entity mentions, never role references, at final rendered positions."""
from __future__ import annotations

import collections

from .common import Issue
from .stages.stage02_plan import privacy_groups


def measure(filled: dict, plan: dict, condition: dict) -> tuple[dict, list[Issue]]:
    groups = privacy_groups(plan)
    sentences = {s["sent_idx"]: s for s in filled["sentences"]}
    starts, position = {}, 0
    for s in filled["sentences"]:
        starts[s["sent_idx"]] = position
        position += len(s["sentence"])
    counts = collections.Counter()
    scenes = collections.defaultdict(set)
    thirds = collections.defaultdict(set)
    per_entity = {}
    repeated = collections.Counter()
    issues = []
    for entity in filled["entities"]:
        eid, privacy = entity["entity_id"], groups[entity["entity_id"]]
        actual_scenes = set()
        actual_thirds = set()
        positions = []
        for mention in entity["mentions"]:
            scene = sentences[mention["sent_idx"]]["scene_id"]
            third = min(2, (starts[mention["sent_idx"]]+mention["begin"]) * 3 // max(1, position))
            counts[privacy] += 1
            scenes[privacy].add(scene)
            thirds[privacy].add(third)
            actual_scenes.add(scene)
            actual_thirds.add(third)
            positions.append({"sent_idx": mention["sent_idx"], "begin": mention["begin"], "scene_id": scene, "document_third": third})
        if len(entity["mentions"]) > 1:
            repeated[privacy] += 1
        per_entity[eid] = {"group": privacy, "entity_type": entity["entity_type"], "mentions": len(entity["mentions"]), "scenes": sorted(actual_scenes), "document_thirds": sorted(actual_thirds), "positions": positions}
        if not entity["mentions"]:
            issues.append(Issue("MISSING_ENTITY_MENTION", "Entity has no actual mention", entity_id=eid))
    total = counts["PII"]+counts["NON_PII"]
    share = counts["PII"] / total if total else 0
    return {"policy": "observe_only", "entity_counts": dict(collections.Counter(groups.values())), "mention_counts": dict(counts), "repeated_entities_by_group": dict(repeated), "pii_mention_share": share, "scenes_by_group": {k: sorted(v) for k,v in scenes.items()}, "thirds_by_group": {k: sorted(v) for k,v in thirds.items()}, "entities": per_entity}, issues
