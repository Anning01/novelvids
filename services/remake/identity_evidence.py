"""Compare explicit source identities across simultaneous episode inventories."""
import unicodedata


IDENTITY_EVIDENCE_FIELD = "cross_episode_identity"
_RELATIONS = {
    "characters": {"spouse", "parent", "child", "sibling"},
    "scenes": {"address"},
    "objects": {"serial"},
}


def identity_anchor(candidate, group, characters):
    value = (candidate.get("visual_fields") or {}).get(IDENTITY_EVIDENCE_FIELD, "")
    relation, sep, target = unicodedata.normalize("NFKC", value).casefold().partition(":")
    target = " ".join(target.split())
    if group == "characters" and target not in characters:
        return None
    if sep and relation.strip() in _RELATIONS[group] and target and len(target) <= 150:
        return relation.strip() + ":" + target
    return None


def identity_name(name):
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())
