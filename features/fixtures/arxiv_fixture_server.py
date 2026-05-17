"""
Local fixture HTTP server that mimics the arxiv Atom API for BDD tests.

Runs in a daemon thread inside the behave process.  One server instance is
created per scenario (via the Background step) and stopped in after_scenario.

Response configuration is keyed by the integer value of the start query
parameter.  Any start value absent from the response table uses the server
defaults: HTTP 200, 50 entries, each with a comment URL.
"""

import http.server
import io
import threading
import urllib.parse
import xml.etree.ElementTree as ET

_ATOM_NS = "http://www.w3.org/2005/Atom"
_ARXIV_NS = "http://arxiv.org/schemas/atom"

ET.register_namespace("", _ATOM_NS)
ET.register_namespace("arxiv", _ARXIV_NS)


def _build_atom_response(n_entries: int, all_have_comment_url: bool) -> bytes:
    """Return a minimal arxiv Atom XML body containing n_entries entries."""
    root = ET.Element(f"{{{_ATOM_NS}}}feed")

    for i in range(n_entries):
        entry = ET.SubElement(root, f"{{{_ATOM_NS}}}entry")

        ET.SubElement(entry, f"{{{_ATOM_NS}}}id").text = (
            f"http://arxiv.org/abs/fixture.{i + 1:06d}v1"
        )
        ET.SubElement(entry, f"{{{_ATOM_NS}}}title").text = (
            f"Fixture Article {i + 1}"
        )

        author = ET.SubElement(entry, f"{{{_ATOM_NS}}}author")
        ET.SubElement(author, f"{{{_ATOM_NS}}}name").text = "Fixture Author"

        primary_cat = ET.SubElement(entry, f"{{{_ARXIV_NS}}}primary_category")
        primary_cat.set("term", "cs.AI")

        link = ET.SubElement(entry, f"{{{_ATOM_NS}}}link")
        link.set("rel", "alternate")
        link.set("type", "text/html")
        link.set("href", f"https://arxiv.org/abs/fixture.{i + 1:06d}v1")

        ET.SubElement(entry, f"{{{_ATOM_NS}}}published").text = (
            "2026-05-12T10:00:00Z"
        )
        ET.SubElement(entry, f"{{{_ATOM_NS}}}updated").text = (
            "2026-05-12T10:00:00Z"
        )

        if all_have_comment_url:
            ET.SubElement(entry, f"{{{_ARXIV_NS}}}comment").text = (
                f"Code at https://github.com/fixture/repo-{i + 1}"
            )

    buf = io.BytesIO()
    ET.ElementTree(root).write(buf, encoding="UTF-8", xml_declaration=True)
    return buf.getvalue()


class ArxivFixtureServer:
    """
    Local HTTP server that mimics the arxiv API for BDD tests.

    The response_table maps integer start values to
    (http_status, n_entries, all_have_comment_url) tuples.  Requests whose
    start value is absent from the table use the server defaults.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Raw request paths (including query strings), in arrival order.
        self._requests: list[str] = []
        # Maps start parameter value to (http_status, n_entries, all_have_url).
        self._response_table: dict[int, tuple[int, int, bool]] = {}
        self._default_status: int = 200
        self._default_n_entries: int = 50
        self._default_all_have_comment_url: bool = True

        handler_class = self._make_handler()
        self._http_server = http.server.HTTPServer(
            ("127.0.0.1", 0), handler_class
        )
        self._port: int = self._http_server.server_address[1]
        self._thread = threading.Thread(
            target=self._http_server.serve_forever,
            daemon=True,
        )
        self._thread.start()

    @property
    def url(self) -> str:
        """Base URL of the fixture server (scheme + host + port, no path)."""
        return f"http://127.0.0.1:{self._port}"

    def set_response(
        self,
        start: int,
        status: int,
        n_entries: int,
        all_have_comment_url: bool = True,
    ) -> None:
        """Configure the response for a specific start parameter value."""
        with self._lock:
            self._response_table[start] = (status, n_entries, all_have_comment_url)

    def get_requests(self) -> list[str]:
        """Return a snapshot of all received request paths with query strings."""
        with self._lock:
            return list(self._requests)

    def stop(self) -> None:
        """Shut down the HTTP server thread."""
        self._http_server.shutdown()

    def _make_handler(self) -> type:
        """Return a BaseHTTPRequestHandler subclass closed over this instance."""
        fixture = self

        class _Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                parsed = urllib.parse.urlparse(self.path)
                params = urllib.parse.parse_qs(
                    parsed.query, keep_blank_values=True
                )
                start_val = int(params.get("start", ["0"])[0])

                with fixture._lock:
                    fixture._requests.append(self.path)
                    if start_val in fixture._response_table:
                        status, n, all_url = fixture._response_table[start_val]
                    else:
                        status = fixture._default_status
                        n = fixture._default_n_entries
                        all_url = fixture._default_all_have_comment_url

                if status == 200:
                    body = _build_atom_response(n, all_url)
                    self.send_response(200)
                    self.send_header(
                        "Content-Type",
                        "application/atom+xml; charset=utf-8",
                    )
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                else:
                    self.send_response(status)
                    self.send_header("Content-Length", "0")
                    self.end_headers()

            def log_message(self, format: str, *args: object) -> None:
                # Suppress default request logging to keep test output clean.
                pass

        return _Handler
