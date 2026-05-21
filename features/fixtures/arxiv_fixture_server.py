"""
Local fixture HTTP server that mimics the arxiv Atom API for BDD tests.

Runs in a daemon thread inside the behave process.  One server instance is
created per scenario (via the Background step) and stopped in after_scenario.

Response resolution order for each incoming request:

1.  If an initial response sequence is configured, the next element is
    consumed regardless of the start query parameter.
2.  Else if the start value is present in the response table, that entry
    is used.
3.  Else the server default response is used.

The initial sequence supports retry-scenario tests where the same start=0
URL must return different statuses on successive calls.
"""

import http.server
import io
import threading
import typing
import urllib.parse
import xml.etree.ElementTree as ET

from atom_ns import ARXIV_NS, ATOM_NS


class Response(typing.NamedTuple):
    """One response policy: HTTP status, entry count, and how many of those entries carry a comment URL."""

    status: int
    n_entries: int
    n_have_comment_url: int


def _resolve_n_have_comment_url(
    n_entries: int, n_have_comment_url: int | None
) -> int:
    """Return n_entries when the caller passed None, otherwise the explicit value."""
    return n_entries if n_have_comment_url is None else n_have_comment_url


def _build_atom_response(
    n_entries: int,
    n_have_comment_url: int,
    primary_category: str,
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


class _FixtureHTTPServer(http.server.HTTPServer):
    """HTTPServer carrying a reference to its owning ArxivFixtureServer.

    The handler reads this attribute via self.server.fixture so that the
    handler class can live at module level instead of being defined as a
    closure over the fixture instance.
    """

    fixture: "ArxivFixtureServer"


class _FixtureRequestHandler(http.server.BaseHTTPRequestHandler):
    """Handle GET requests by consulting the fixture's response policy."""

    server: _FixtureHTTPServer  # narrowed type for self.server

    def do_GET(self) -> None:
        """Serve one Atom XML response based on the fixture's resolution order."""
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        start_val = int(params.get("start", ["0"])[0])

        response, primary_category = self.server.fixture._next_response(
            self.path, start_val
        )

        if response.status == 200:
            body = _build_atom_response(
                response.n_entries,
                response.n_have_comment_url,
                primary_category,
            )
            self.send_response(200)
            self.send_header(
                "Content-Type", "application/atom+xml; charset=utf-8"
            )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(response.status)
            self.send_header("Content-Length", "0")
            self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        """Suppress default request logging to keep test output clean."""
        return


class ArxivFixtureServer:
    """
    Local HTTP server that mimics the arxiv API for BDD tests.

    Resolution order per request is documented at module level: initial
    response sequence first, then start-keyed table, then the single
    default response.  The primary category applied to generated entries
    is a server-wide setting (default "cs.AI").
    """

    _DEFAULT_RESPONSE = Response(status=200, n_entries=10, n_have_comment_url=10)
    _DEFAULT_PRIMARY_CATEGORY = "cs.AI"

    def __init__(self) -> None:
        """Start the fixture server on an ephemeral localhost port in a daemon thread."""
        self._lock = threading.Lock()
        self._requests: list[str] = []
        self._response_table: dict[int, Response] = {}
        self._initial_responses: list[Response] = []
        self._default: Response = self._DEFAULT_RESPONSE
        self._primary_category: str = self._DEFAULT_PRIMARY_CATEGORY

        self._http_server = _FixtureHTTPServer(
            ("127.0.0.1", 0), _FixtureRequestHandler
        )
        self._http_server.fixture = self
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

        n_have_comment_url defaults to n_entries (all entries get a URL)
        when not set.
        """
        response = Response(
            status=status,
            n_entries=n_entries,
            n_have_comment_url=_resolve_n_have_comment_url(
                n_entries, n_have_comment_url
            ),
        )
        with self._lock:
            self._response_table[start] = response

    def set_initial_response_sequence(
        self, responses: list[tuple[int, int, int]]
    ) -> None:
        """
        Set a sequence of responses to return for the first len(responses)
        requests, regardless of their start parameter value.

        Each element is (http_status, n_entries, n_have_comment_url).
        Once the sequence is exhausted, subsequent requests fall through to
        the start-based response table and the server default.
        """
        with self._lock:
            self._initial_responses = [
                Response(status=s, n_entries=n, n_have_comment_url=u)
                for s, n, u in responses
            ]

    def set_default(
        self,
        status: int,
        n_entries: int,
        n_have_comment_url: int | None = None,
    ) -> None:
        """
        Override the default response returned when neither the initial
        sequence nor the per-start table matches.

        n_have_comment_url defaults to n_entries (all entries get a URL)
        when not set.
        """
        response = Response(
            status=status,
            n_entries=n_entries,
            n_have_comment_url=_resolve_n_have_comment_url(
                n_entries, n_have_comment_url
            ),
        )
        with self._lock:
            self._default = response

    def set_default_primary_category(self, primary_category: str) -> None:
        """
        Set the arxiv primary category applied to all generated fixture entries.

        Affects responses from the initial sequence, the start-based table,
        and the server default.  Default value is "cs.AI".
        """
        with self._lock:
            self._primary_category = primary_category

    def get_requests(self) -> list[str]:
        """Return a snapshot of all received request paths with query strings."""
        with self._lock:
            return list(self._requests)

    def stop(self) -> None:
        """Shut down the HTTP server thread."""
        self._http_server.shutdown()

    def _next_response(
        self, request_path: str, start_val: int
    ) -> tuple[Response, str]:
        """
        Record the request and return (response, primary_category) under lock.

        The initial sequence has highest precedence (consumed once per
        request), then the start-keyed table, then the default.
        """
        with self._lock:
            self._requests.append(request_path)
            if self._initial_responses:
                response = self._initial_responses.pop(0)
            elif start_val in self._response_table:
                response = self._response_table[start_val]
            else:
                response = self._default
            return response, self._primary_category
