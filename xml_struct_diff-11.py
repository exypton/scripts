#!/usr/bin/python
# action_plugins/xml_struct_diff.py

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

from ansible.plugins.action import ActionBase
import re
import xml.etree.ElementTree as ET
import difflib
from copy import deepcopy

class ActionModule(ActionBase):
    def run(self, tmp=None, task_vars=None):
        if task_vars is None:
            task_vars = dict()

        result = super(ActionModule, self).run(tmp, task_vars)
        del tmp  # tmp no longer has any effect

        # 1. Get Arguments from Task
        before_xml = self._task.args.get('before', '')
        after_xml = self._task.args.get('after', '')

        # 2. Logic Implementation (Encapsulated)
        def compute_diff(before_str, after_str):
            # Tags that should always be shown if their parent is modified
            CONTEXT_TAGS = {'name', 'id', 'description', 'type', 'vlan-id'}

            def escape_html(s):
                if not s: return ""
                return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

            node_keys = {}

            def sort_and_key(node):
                child_keys = []
                for child in node:
                    child_keys.append(sort_and_key(child))
                
                if child_keys:
                    children_with_keys = sorted(zip(node, child_keys), key=lambda x: x[1])
                    node[:] = [x[0] for x in children_with_keys]
                    my_sorted_child_keys = tuple(x[1] for x in children_with_keys)
                else:
                    my_sorted_child_keys = ()

                my_key = (
                    node.tag, 
                    tuple(sorted(node.attrib.items())), 
                    (node.text or "").strip(),
                    my_sorted_child_keys
                )
                node_keys[node] = my_key
                return my_key

            def parse_clean(xml_str):
                if not xml_str or not xml_str.strip():
                    return None
                # Basic namespace stripping
                clean_xml = re.sub(r' xmlns="[^"]+"', '', xml_str, count=0)
                clean_xml = re.sub(r' xmlns:[a-z0-9]+="[^"]+"', '', clean_xml, count=0)
                try:
                    root = ET.fromstring(clean_xml)
                    sort_and_key(root)
                    return root
                except ET.ParseError:
                    return None

            root_before = parse_clean(before_str)
            root_after = parse_clean(after_str)

            stats = {"added": 0, "removed": 0, "modified": 0}

            def count_lines(elem, is_leaf=False):
                if elem is None: return 0
                if is_leaf: return 1 
                lines = 2 
                if elem.text and elem.text.strip():
                    lines += 1
                for child in elem:
                    child_is_leaf = (len(child) == 0)
                    lines += count_lines(child, child_is_leaf)
                return lines

            def mark_tree(element, style):
                if element is None: return
                if element.text and element.text.strip():
                    element.text = '<span style="{} font-weight:bold;">{}</span>'.format(style, escape_html(element.text))
                element.set('__diff_style__', style)
                for child in element:
                    mark_tree(child, style)

            def compare_nodes(node_a, node_b):
                if node_a is None and node_b is None:
                    return (None, None, False)

                # Node Removed
                if node_b is None:
                    stats["removed"] += 1
                    res_a = deepcopy(node_a)
                    mark_tree(res_a, "color:#cc0000;")
                    lines = count_lines(res_a, len(res_a) == 0)
                    res_b_spacer = ET.Element("__spacer__", lines=str(lines))
                    return (res_a, res_b_spacer, True)

                # Node Added
                if node_a is None:
                    stats["added"] += 1
                    res_b = deepcopy(node_b)
                    mark_tree(res_b, "color:#00aa00;")
                    lines = count_lines(res_b, len(res_b) == 0)
                    res_a_spacer = ET.Element("__spacer__", lines=str(lines))
                    return (res_a_spacer, res_b, True)

                # Tag Mismatch (Structural Difference)
                if node_a.tag != node_b.tag:
                    stats["removed"] += 1
                    stats["added"] += 1
                    res_a = deepcopy(node_a)
                    res_b = deepcopy(node_b)
                    mark_tree(res_a, "color:#cc0000;")
                    mark_tree(res_b, "color:#00aa00;")
                    
                    lines_a = count_lines(res_a, len(res_a)==0)
                    lines_b = count_lines(res_b, len(res_b)==0)
                    
                    if lines_a < lines_b:
                        res_a.set('__append_spacer__', str(lines_b - lines_a))
                    elif lines_b < lines_a:
                        res_b.set('__append_spacer__', str(lines_a - lines_b))
                        
                    return (res_a, res_b, True)

                # Attributes & Text
                text_a = (node_a.text or "").strip()
                text_b = (node_b.text or "").strip()
                is_modified = text_a != text_b
                
                if node_a.attrib != node_b.attrib:
                    is_modified = True

                out_a = ET.Element(node_a.tag, attrib=node_a.attrib)
                out_b = ET.Element(node_b.tag, attrib=node_b.attrib)
                
                children_a = list(node_a)
                children_b = list(node_b)
                
                keys_a = [node_keys.get(c) for c in children_a]
                keys_b = [node_keys.get(c) for c in children_b]

                matcher = difflib.SequenceMatcher(None, keys_a, keys_b)
                has_child_changes = False

                for tag, i1, i2, j1, j2 in matcher.get_opcodes():
                    if tag == 'equal':
                        for k in range(i2 - i1):
                            c_a = children_a[i1 + k]
                            c_b = children_b[j1 + k]
                            
                            # Preserve Context Tags
                            if c_a.tag in CONTEXT_TAGS:
                                res_ctxt_a = deepcopy(c_a)
                                res_ctxt_b = deepcopy(c_b)
                                res_ctxt_a.text = escape_html((c_a.text or "").strip())
                                res_ctxt_b.text = escape_html((c_b.text or "").strip())
                                # No visual style mark, just append
                                out_a.append(res_ctxt_a)
                                out_b.append(res_ctxt_b)
                            else:
                                child_res_a, child_res_b, changed = compare_nodes(c_a, c_b)
                                if changed:
                                    has_child_changes = True
                                    out_a.append(child_res_a)
                                    out_b.append(child_res_b)
                                
                    elif tag == 'replace':
                        len_a = i2 - i1
                        len_b = j2 - j1
                        min_len = min(len_a, len_b)
                        
                        for k in range(min_len):
                            c_a = children_a[i1 + k]
                            c_b = children_b[j1 + k]
                            
                            if c_a.tag == c_b.tag:
                                child_res_a, child_res_b, changed = compare_nodes(c_a, c_b)
                                if changed:
                                    has_child_changes = True
                                    out_a.append(child_res_a)
                                    out_b.append(child_res_b)
                            else:
                                res_a, res_b_spacer, _ = compare_nodes(c_a, None)
                                res_a_spacer, res_b, _ = compare_nodes(None, c_b)
                                has_child_changes = True
                                out_a.append(res_a)
                                out_b.append(res_b_spacer)
                                out_a.append(res_a_spacer)
                                out_b.append(res_b)
                        
                        if len_a > len_b:
                            for k in range(min_len, len_a):
                                c_a = children_a[i1 + k]
                                res_a, res_b_spacer, _ = compare_nodes(c_a, None)
                                has_child_changes = True
                                out_a.append(res_a)
                                out_b.append(res_b_spacer)
                        elif len_b > len_a:
                            for k in range(min_len, len_b):
                                c_b = children_b[j1 + k]
                                res_a_spacer, res_b, _ = compare_nodes(None, c_b)
                                has_child_changes = True
                                out_a.append(res_a_spacer)
                                out_b.append(res_b)
                    
                    elif tag == 'delete':
                        for k in range(i1, i2):
                            c_a = children_a[k]
                            res_a, res_b_spacer, _ = compare_nodes(c_a, None)
                            has_child_changes = True
                            out_a.append(res_a)
                            out_b.append(res_b_spacer)
                    
                    elif tag == 'insert':
                        for k in range(j1, j2):
                            c_b = children_b[k]
                            res_a_spacer, res_b, _ = compare_nodes(None, c_b)
                            has_child_changes = True
                            out_a.append(res_a_spacer)
                            out_b.append(res_b)

                if is_modified:
                    stats["modified"] += 1
                    out_a.text = '<span style="color:#ff8800; font-weight:bold;">{}</span>'.format(escape_html(text_a))
                    out_b.text = '<span style="color:#ff8800; font-weight:bold;">{}</span>'.format(escape_html(text_b))
                    out_a.set('__diff_style__', 'color:#ff8800;') 
                    out_b.set('__diff_style__', 'color:#ff8800;')
                else:
                    out_a.text = escape_html(text_a)
                    out_b.text = escape_html(text_b)
                
                if not is_modified and not has_child_changes:
                    return (None, None, False)
                    
                return (out_a, out_b, True)

            result_left, result_right, any_change = compare_nodes(root_before, root_after)

            def serialize(elem, level=0):
                if elem is None: return ""
                if elem.tag == "__spacer__":
                    lines = int(elem.get('lines', 1))
                    return "".join(['<div class="spacer">&nbsp;</div>' for _ in range(lines)])

                indent_style = "padding-left: {}px;".format(level * 20)
                
                attrs = ""
                for k, v in elem.attrib.items():
                    if not k.startswith('__'):
                        val = escape_html(v).replace('"', '&quot;')
                        attrs += ' {}="{}"'.format(k, val)
                
                tag_style = elem.get('__diff_style__') or "color: #6b7280;"
                
                start_tag_html = '<span style="{}">&lt;{}{}&gt;</span>'.format(tag_style, elem.tag, attrs)
                end_tag_html = '<span style="{}">&lt;/{}&gt;</span>'.format(tag_style, elem.tag)
                
                append_spacer = int(elem.get('__append_spacer__', 0))
                spacer_html = "".join(['<div class="spacer">&nbsp;</div>' for _ in range(append_spacer)])

                if len(elem) == 0:
                    content_html = elem.text or ""
                    if not content_html.startswith('<span'):
                        content_html = '<span style="color: #374151;">{}</span>'.format(content_html)
                    return '<div style="{}">{}{}{}</div>{}'.format(indent_style, start_tag_html, content_html, end_tag_html, spacer_html)
                
                out = '<div style="{}">{}</div>'.format(indent_style, start_tag_html)
                
                if elem.text and elem.text.strip():
                    text_indent = "padding-left: {}px;".format((level * 20) + 20)
                    text_content = elem.text.strip()
                    if not text_content.startswith('<span'):
                        text_content = '<span style="color: #374151;">{}</span>'.format(text_content)
                    out += '<div style="{}">{}</div>'.format(text_indent, text_content)
                    
                for child in elem:
                    out += serialize(child, level + 1)
                    
                out += '<div style="{}">{}</div>'.format(indent_style, end_tag_html)
                out += spacer_html
                return out

            return {
                "left": serialize(result_left) or '<div class="text-gray-400 italic p-4">No Changes</div>',
                "right": serialize(result_right) or '<div class="text-gray-400 italic p-4">No Changes</div>',
                "metadata": {
                    "changed": any_change,
                    "added_count": stats["added"],
                    "removed_count": stats["removed"],
                    "changed_count": stats["modified"]
                }
            }

        # 3. Execute and Return
        diff_output = compute_diff(before_xml, after_xml)
        
        # Populate the Ansible Result
        result.update(diff_output)
        result['changed'] = diff_output['metadata']['changed']
        
        return result
