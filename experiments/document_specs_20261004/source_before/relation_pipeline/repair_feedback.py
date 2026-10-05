"""Convert known filled values in review feedback back to registered tokens.

Only the prompt view is changed. Raw review, actual body, labels and value map
remain untouched. Ambiguous identical surfaces are deliberately not assigned.
"""
import collections
import re


def mask_known_feedback(value,plan,values):
    tokens=collections.defaultdict(set)
    for entity in plan['entities']:
        item=values.get(entity['entity_id'],{})
        for surface in (item.get('value'),item.get('canonical_form')):
            if isinstance(surface,str) and surface:
                tokens[surface].add(f"<{entity['entity_type']}:{entity['entity_id']}>")
    replacements={surface:next(iter(tags)) for surface,tags in tokens.items() if len(tags)==1}
    if not replacements:
        return value
    pattern=re.compile(r'<[^<>]+>|'+ '|'.join(re.escape(s) for s in sorted(replacements,key=len,reverse=True)))
    def walk(obj):
        if isinstance(obj,str):
            return pattern.sub(lambda m:replacements.get(m[0],m[0]),obj)
        if isinstance(obj,list):
            return [walk(v) for v in obj]
        if isinstance(obj,dict):
            return {k:walk(v) for k,v in obj.items()}
        return obj
    return walk(value)
