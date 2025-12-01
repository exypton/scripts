from xmldiff import main, formatting
from lxml import etree
import json
import io

def parse_without_ns(xml_str):
    """
    Robust namespace-stripping XML parser for NETCONF/YANG data.
    Ensures the final root element is returned correctly.
    """

    # Streaming parse
    it = etree.iterparse(
        io.BytesIO(xml_str.encode("utf-8")),
        events=("start", "end"),
        remove_blank_text=True
    )

    root = None

    for event, el in it:

        # Capture root on the first 'start' event
        if event == "start" and root is None:
            root = el

        # Remove element namespace
        if '}' in el.tag:
            el.tag = el.tag.split('}', 1)[1]

        # Remove attribute namespaces
        new_attrs = {}
        for attr, val in el.attrib.items():
            if '}' in attr:
                attr = attr.split('}', 1)[1]
            new_attrs[attr] = val

        el.attrib.clear()
        el.attrib.update(new_attrs)

    return root

class StructuredFormatter(formatting.XMLFormatter):

    def __init__(self):
        super().__init__()
        self.output = {
            "added": [],
            "deleted": [],
            "changed": [],
            "moved": []
        }

        # Prevent namespace lookup inside xmldiff
        self.namespaces = {}

    def append(self, op, node):

        if op == "insert":
            # node is a tuple (path, xml-string, position)
            path = node[0]
            self.output["added"].append(path)

        elif op == "delete":
            path = node[0]
            self.output["deleted"].append(path)

        elif op == "update":
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

    before_doc = parse_without_ns(before_xml)
    after_doc = parse_without_ns(after_xml)

    formatter = StructuredFormatter()

    # IMPORTANT: disable namespace-dependent algorithms in xmldiff
    diff = main.diff_trees(
        before_doc,
        after_doc,
        formatter=formatter,
        diff_options={
            "F": 0.5,
            "ratio_mode": "fast",
            "uniqueattrs": [],        # disable namespace-based uniqueness
            "explicit_namespaces": {},# disable namespace resolution
        }
    )

    return json.loads(formatter.tostring())


class FilterModule(object):
    def filters(self):
        return {
            "xml_structured_diff": structured_xml_diff
        }
