"""
Shared Atom namespace constants for step definitions and the fixture server.

The two `ET.register_namespace` calls below run once at module import time
and ensure that `xml.etree.ElementTree.write(...)` emits `<feed xmlns="...">`
and `<arxiv:comment>` rather than the auto-generated `ns0:`/`ns1:` prefixes.

Step files and the fixture server import the constants from here rather than
defining their own copies so the prefix registration cannot drift between
modules.
"""

import xml.etree.ElementTree as ET

ATOM_NS = "http://www.w3.org/2005/Atom"
ARXIV_NS = "http://arxiv.org/schemas/atom"

ET.register_namespace("", ATOM_NS)
ET.register_namespace("arxiv", ARXIV_NS)
