"""Observe minimal evidence in final sentence order; never allocate expression quotas."""
from __future__ import annotations


def observed_expression(groups: list[list[str]], positions: dict[str, int]) -> dict:
    valid = [g for g in groups if g and len(g) == len(set(g)) and all(sid in positions for sid in g)]
    ordered = [sorted(positions[sid] for sid in group) for group in valid]
    if any(len(g) == 1 for g in valid):
        mode = "single"
    elif any(all(b-a == 1 for a,b in zip(group,group[1:])) for group in ordered):
        mode = "adjacent"
    elif valid:
        mode = "nonadjacent"
    else:
        mode = "unresolved"
    return {"observed_mode": mode, "minimum_size": min(map(len, valid), default=None),
            "final_order_positions": ordered}
