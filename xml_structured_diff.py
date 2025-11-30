from xmldiff import main, formatting
from lxml import etree
import json
import re

class StructuredFormatter(formatting.XMLFormatter):
    """
    Converts xmldiff operations into structured change records:
    - added
    - deleted
    - changed (old/new value extracted)
    - moved
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
        """
        xmldiff operations map into our structured model:
        - insert → added
        - delete → deleted
        - update → changed (old/new values parsed)
        - move → moved
        """
        if op == "insert":
            self.output["added"].append(node)

        elif op == "delete":
            self.output["deleted"].append(node)

        elif op == "update":
            # node example: "/xpath/to/element", "old", "new"
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

        else:
            self.output.setdefault("other", []).append({"op": op, "node": node})

    def tostring(self):
        return json.dumps(self.output, indent=2)


def structured_xml_diff(before_xml, after_xml):
    """
    Performs a structural XML diff between two XML strings.
    Returns a Python dict with grouped and parsed diff operations.
    """

    before_doc = etree.fromstring(before_xml.encode("utf-8"))
    after_doc = etree.fromstring(after_xml.encode("utf-8"))

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
