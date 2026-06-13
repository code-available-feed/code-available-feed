"""
Local fixture HTTP server that mimics the arxiv Atom API for BDD tests.

Runs in a daemon thread inside the behave process.  One server instance is
created per scenario (via the Background step) and stopped in after_scenario.

Each request is resolved as follows:

1.  If a non-empty queue is configured for the request's start query
    parameter, the next queued Response is popped and used.
2.  Otherwise the server's single default Response is used.

A queue holds zero or more pre-configured Responses for a given start
value.  This single mechanism supports both pagination tests (one
Response queued per distinct start) and retry tests (multiple Responses
queued for start=0, popped one per retry until the queue drains and
subsequent retries hit the default).
"""

import http.server
import io
import threading
import typing
import urllib.parse
import xml.etree.ElementTree as ET

from atom_ns import ARXIV_NS, ATOM_NS


class Response(typing.NamedTuple):
    """One response policy: HTTP status, entry count, URL distribution, and optional raw body.

    When raw_body is not None the server sends it verbatim as the response body (for status 200)
    instead of generating an Atom XML document via _build_atom_response.  This allows tests to
    exercise malformed-XML code paths without modifying the Atom generator.

    Entry URL assignment order (0-based index i):
      i < n_have_comment_url                              -> comment element with https://code.example.com/...
      n_have_comment_url <= i < n_have_comment_url + n_have_abstract_url -> summary with https://github.com/... (accepted domain)
      otherwise                                           -> plain abstract text, no code URL
    """

    status: int
    n_entries: int
    n_have_comment_url: int
    n_have_abstract_url: int = 0
    raw_body: bytes | None = None


def _build_atom_response(
    n_entries: int,
    n_have_comment_url: int,
    n_have_abstract_url: int,
    primary_category: str,
) -> bytes:
    """Return a minimal arxiv Atom XML body containing n_entries entries.

    Entry URL assignment follows the Response docstring ordering:
    - i < n_have_comment_url: comment element with https://code.example.com/fixture/repo-N
    - n_have_comment_url <= i < n_have_comment_url + n_have_abstract_url:
        summary with https://github.com/fixture/repo-N (accepted domain for abstract cascade)
    - otherwise: plain summary text with no accepted-domain URL
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

        abstract_url_boundary = n_have_comment_url + n_have_abstract_url
        if n_have_comment_url <= i < abstract_url_boundary:
            ET.SubElement(entry, f"{{{ATOM_NS}}}summary").text = (
                f"Code at https://github.com/fixture/repo-{i + 1}"
            )
        else:
            ET.SubElement(entry, f"{{{ATOM_NS}}}summary").text = (
                f"Abstract text for fixture article {i + 1}."
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
            body = (
                response.raw_body
                if response.raw_body is not None
                else _build_atom_response(
                    response.n_entries,
                    response.n_have_comment_url,
                    response.n_have_abstract_url,
                    primary_category,
                )
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

    Resolution order per request is documented at module level: pop one
    Response from the queue for the request's start value if non-empty,
    otherwise use the single default Response.  The primary category
    applied to generated entries is a server-wide setting (default "cs.AI").
    """

    _DEFAULT_RESPONSE = Response(status=200, n_entries=10, n_have_comment_url=10)
    _DEFAULT_PRIMARY_CATEGORY = "cs.AI"

    def __init__(self) -> None:
        """Start the fixture server on an ephemeral localhost port in a daemon thread."""
        self._lock = threading.Lock()
        self._requests: list[str] = []
        # Maps start parameter value to a FIFO queue of Responses; each
        # request to that start value pops one entry from the queue, and
        # when empty (or absent) the request falls through to _default.
        self._queues: dict[int, list[Response]] = {}
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
        n_have_abstract_url: int = 0,
    ) -> None:
        """Queue one response for the given start parameter value.

        n_have_comment_url defaults to n_entries (all entries get a comment URL)
        when not set.  n_have_abstract_url defaults to 0.  Each call appends one
        Response to the queue for that start value; the request handler pops one
        per request.  When the queue is drained, subsequent requests for the same
        start value fall through to the default response.
        """
        response = Response(
            status=status,
            n_entries=n_entries,
            n_have_comment_url=(
                n_entries if n_have_comment_url is None else n_have_comment_url
            ),
            n_have_abstract_url=n_have_abstract_url,
        )
        with self._lock:
            self._queues.setdefault(start, []).append(response)

    def set_raw_body_response(self, start: int, status: int, body: bytes) -> None:
        """
        Queue one response for the given start value that sends body verbatim.

        Useful for simulating responses that are HTTP 200 but carry malformed XML.
        """
        response = Response(
            status=status,
            n_entries=0,
            n_have_comment_url=0,
            raw_body=body,
        )
        with self._lock:
            self._queues.setdefault(start, []).append(response)

    def set_default(
        self,
        status: int,
        n_entries: int,
        n_have_comment_url: int | None = None,
        n_have_abstract_url: int = 0,
    ) -> None:
        """Override the default response returned when the request's start value
        has no queue or its queue has been drained.

        n_have_comment_url defaults to n_entries (all entries get a comment URL)
        when not set.  n_have_abstract_url defaults to 0.
        """
        response = Response(
            status=status,
            n_entries=n_entries,
            n_have_comment_url=(
                n_entries if n_have_comment_url is None else n_have_comment_url
            ),
            n_have_abstract_url=n_have_abstract_url,
        )
        with self._lock:
            self._default = response

    def set_default_primary_category(self, primary_category: str) -> None:
        """
        Set the arxiv primary category applied to all generated fixture entries.

        Affects every response served by this fixture instance, whether
        popped from a queue or taken from the default.  Default value is "cs.AI".
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

        The queue for start_val is consumed once per request; when the
        queue is empty or absent, the request falls through to the single
        default response.
        """
        with self._lock:
            self._requests.append(request_path)
            queue = self._queues.get(start_val)
            if queue:
                response = queue.pop(0)
            else:
                response = self._default
            return response, self._primary_category
