"""
Local fixture HTTP server that mimics the arxiv Atom API for BDD tests.

Runs in a daemon thread inside the behave process.  One server instance is
created per scenario (via the Background step) and stopped in after_scenario.

Response configuration is keyed by the integer value of the start query
parameter.  Any start value absent from the response table uses the server
defaults: HTTP 200, 10 entries, each with a comment URL.

An optional initial response sequence (set via set_initial_response_sequence)
takes precedence over the start-based table for the first N requests,
regardless of their start parameter values.  This supports retry-scenario
testing where the same start=0 URL must return different statuses on
successive calls.
"""

import http.server
import io
import threading
import urllib.parse
import xml.etree.ElementTree as ET

from atom_ns import ARXIV_NS, ATOM_NS


def _build_atom_response(
    n_entries: int,
    n_have_comment_url: int,
    primary_category: str = "cs.AI",
) -> bytes:
    """
    Return a minimal arxiv Atom XML body containing n_entries entries.

    The first n_have_comment_url entries include a comment field with an
    https:// URL; the remainder do not.  Pass n_entries to give all entries
    a comment URL; pass 0 to give none.
    """
    root = ET.Element(f"{{{ATOM_NS}}}feed")

    for i in range(n_entries):
        entry = ET.SubElement(root, f"{{{ATOM_NS}}}entry")

        ET.SubElement(entry, f"{{{ATOM_NS}}}id").text = (
            f"http://arxiv.org/abs/fixture.{i + 1:06d}v1"
        )
        ET.SubElement(entry, f"{{{ATOM_NS}}}title").text = (
            f"Fixture Article {i + 1}"
        )

        author = ET.SubElement(entry, f"{{{ATOM_NS}}}author")
        ET.SubElement(author, f"{{{ATOM_NS}}}name").text = "Fixture Author"

        primary_cat = ET.SubElement(entry, f"{{{ARXIV_NS}}}primary_category")
        primary_cat.set("term", primary_category)

        link = ET.SubElement(entry, f"{{{ATOM_NS}}}link")
        link.set("rel", "alternate")
        link.set("type", "text/html")
        link.set("href", f"https://arxiv.org/abs/fixture.{i + 1:06d}v1")

        ET.SubElement(entry, f"{{{ATOM_NS}}}published").text = (
            "2026-05-12T10:00:00Z"
        )
        ET.SubElement(entry, f"{{{ATOM_NS}}}updated").text = (
            "2026-05-12T10:00:00Z"
        )

        if i < n_have_comment_url:
            ET.SubElement(entry, f"{{{ARXIV_NS}}}comment").text = (
                f"Code at https://code.example.com/fixture/repo-{i + 1}"
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

    An initial response sequence (if set) is consumed in arrival order before
    the start-based table is consulted, enabling retry-scenario tests where
    successive requests to the same URL must return different statuses.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        # Raw request paths (including query strings), in arrival order.
        self._requests: list[str] = []
        # Maps start parameter value to (http_status, n_entries, n_have_url).
        self._response_table: dict[int, tuple[int, int, int]] = {}
        # Consumed in order before _response_table is consulted.
        self._initial_responses: list[tuple[int, int, int]] = []
        self._default_status: int = 200
        self._default_n_entries: int = 10
        # Default: all entries have a comment URL (equals n_entries per request).
        # A value of -1 is a sentinel meaning "use n_entries for this response".
        self._default_n_have_comment_url: int = -1
        # Primary category applied to all generated entries.
        self._default_primary_category: str = "cs.AI"

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
        n_have_comment_url: int | None = None,
    ) -> None:
        """
        Configure the response for a specific start parameter value.

        n_have_comment_url is the count of entries that include a comment
        URL; defaults to n_entries (all entries get a URL) when not set.
        """
        actual = n_entries if n_have_comment_url is None else n_have_comment_url
        with self._lock:
            self._response_table[start] = (status, n_entries, actual)

    def set_initial_response_sequence(
        self, responses: list[tuple[int, int, int]]
    ) -> None:
        """
        Set a sequence of responses to return for the first len(responses)
        requests, regardless of their start parameter value.

        Each element is (http_status, n_entries, n_have_comment_url).
        Once the sequence is exhausted, subsequent requests fall through to
        the start-based response table and server defaults.
        """
        with self._lock:
            self._initial_responses = list(responses)

    def set_default(
        self,
        status: int,
        n_entries: int,
        n_have_comment_url: int | None = None,
    ) -> None:
        """
        Override the default response returned when no explicit per-start
        configuration matches and the initial sequence is exhausted.

        n_have_comment_url defaults to -1 (sentinel for "all entries") when
        not set.
        """
        with self._lock:
            self._default_status = status
            self._default_n_entries = n_entries
            self._default_n_have_comment_url = (
                -1 if n_have_comment_url is None else n_have_comment_url
            )

    def set_default_primary_category(self, primary_category: str) -> None:
        """
        Set the arxiv primary category applied to all generated fixture entries.

        Affects responses from the initial sequence, the start-based table,
        and the server defaults.  Default value is "cs.AI".
        """
        with self._lock:
            self._default_primary_category = primary_category

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
                    if fixture._initial_responses:
                        # Consume the next response from the initial sequence
                        # before checking the start-based table.
                        status, n, n_url = fixture._initial_responses.pop(0)
                    elif start_val in fixture._response_table:
                        status, n, n_url = fixture._response_table[start_val]
                    else:
                        status = fixture._default_status
                        n = fixture._default_n_entries
                        n_url = fixture._default_n_have_comment_url
                    # Sentinel -1 means "give all entries a comment URL".
                    actual_n_url = n if n_url == -1 else n_url
                    primary_category = fixture._default_primary_category

                if status == 200:
                    body = _build_atom_response(n, actual_n_url, primary_category)
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
