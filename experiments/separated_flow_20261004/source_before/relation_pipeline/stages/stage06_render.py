"""Input: assembly/value map. Output: actual text/spans and early dedup decision."""
from ..common import fail
from ..renderer import render


def fill_and_check(assembled: dict, condition: dict, plan: dict, values: dict, dedup, candidate: str):
    filled = render(assembled["draft"], plan, values)
    if filled["rendered_chars"] != assembled["checks"]["metrics"]["rendered_chars"]:
        fail("DRY_RENDER_MISMATCH", "Dry render and final render differ", "CODE_FIX", True)
    if filled["rendered_chars"] < condition["min_chars"]:
        fail("FINAL_LENGTH_SHORTAGE", "Final output below minimum", "CODE_FIX", True)
    return filled, dedup.document_check(filled,condition,candidate)
