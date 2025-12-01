from xmldiff import main, formatting
from lxml import etree
import json
import re


def remove_namespaces(xml_str):
    """
    Removes namespaces from XML to avoid XPathEvalError caused by namespace prefixes.
    """
    parser = etree.XMLParser(remove_blank_text=True)
    root = etree.fromstring(xml_str.encode("utf-8"), parser)

    for elem in root.getiterator():
        if not hasattr(elem.tag, 'find'):
            continue
        i = elem.tag.find('}')
        if i > 0:
            elem.tag = elem.tag[i+1:]  # strip namespace

        # clean namespace declarations
        attribs = elem.attrib
        for attr in list(attribs):
            if attr.startswith("{"):
                new_attr = attr.split("}", 1)[1]
                attribs[new_attr] = attribs[attr]
                del attribs[attr]

    return etree.tostring(root, encoding="unicode")


class StructuredFormatter(formatting.XMLFormatter):
    """
    Converts xmldiff operations into structured change records.
    """

    def __init__(self):
        super().__init__()
        self.output = {
            "added": [],
            "deleted": [],
            "changed": [],
            "moved": []
        }

    def append(self, op, node):
        if op == "insert":
            self.output["added"].append(node)

        elif op == "delete":
            self.output["deleted"].append(node)

        elif op == "update":
            # node = (path, old, new)
            path = node[0]
            old_val = node[1]
            new_val = node[2]
            self.output["changed"].append({
                "path": path,
                "old": old_val,
                "new": new_val
            })

        elif op == "move":
            self.output["moved"].append(node)

    def tostring(self):
        return json.dumps(self.output, indent=2)


def structured_xml_diff(before_xml, after_xml):
    """
    Performs a namespace-safe structural XML diff.
    """

    before_clean = remove_namespaces(before_xml)
    after_clean = remove_namespaces(after_xml)

    before_doc = etree.fromstring(before_clean.encode("utf-8"))
    after_doc = etree.fromstring(after_clean.encode("utf-8"))

    formatter = StructuredFormatter()

    main.diff_trees(
        before_doc,
        after_doc,
        formatter=formatter,
        diff_options={"F": 0.5, "ratio_mode": "fast"},
    )

    return json.loads(formatter.tostring())


class FilterModule(object):
    def filters(self):
        return {
            "xml_structured_diff": structured_xml_diff
        }
