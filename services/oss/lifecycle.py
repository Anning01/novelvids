"""Merge a prefix-scoped cleanup rule while retaining every unrelated bucket rule."""
from xml.etree import ElementTree as ET

RULE_ID = "novelvids-studio-temporary-expire"
TEMP_PREFIX = "studio-temporary/v1/"


def with_temporary_expiry(document: bytes | None) -> bytes:
    root = ET.fromstring(document) if document else ET.Element("LifecycleConfiguration")
    if root.tag != "LifecycleConfiguration":
        raise ValueError("Unexpected OSS lifecycle document")
    for rule in list(root):
        if rule.tag != "Rule":
            raise ValueError("Unexpected OSS lifecycle entry")
        if rule.findtext("ID") == RULE_ID:
            prefix = rule.findtext("Prefix") or rule.findtext("Filter/Prefix")
            if prefix != TEMP_PREFIX:
                raise ValueError("Lifecycle rule ID belongs to another prefix")
            root.remove(rule)
    rule = ET.SubElement(root, "Rule")
    for key,value in (("ID", RULE_ID), ("Prefix", TEMP_PREFIX), ("Status", "Enabled")):
        ET.SubElement(rule, key).text = value
    ET.SubElement(ET.SubElement(rule, "Expiration"), "Days").text = "2"
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)
