"""Ultronova povezava s spletom - po Tor omrežju, brez dodatnih knjižnic.

Iskanje in branje strani gresta lahko skozi Tor SOCKS5 proxy (isto omrežje kot Tor
Browser), z oddaljenim razreševanjem imen (DNS pri izhodnem vozlišču), da nič ne
uhaja mimo Tora. Na Whonixu je ves promet že prisiljen skozi Tor, zato deluje samodejno.
"""

from __future__ import annotations

import functools
import http.client
import ipaddress
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional

USER_AGENT = "UltronLocalAI/2.0 (+https://github.com/BigWhiteNinja08/Ultron)"
# Tor Browser fingerprints its users as a common browser string; we mirror that.
BROWSER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; rv:128.0) Gecko/20100101 Firefox/128.0"
)
HTTP_TIMEOUT = 25  # Tor circuits are slower than a direct connection
MAX_PAGE_BYTES = 2_000_000

# Tor daemon listens on 9050; Tor Browser exposes its own Tor on 9150.
DEFAULT_TOR_PORTS = (9050, 9150)


class NetError(Exception):
    """A network address was refused or unreachable."""


# ---------------------------------------------------------------- SOCKS5 (Tor)

def _parse_proxy(value: str) -> tuple[str, int]:
    value = value.strip()
    if "://" in value:
        value = value.split("://", 1)[1]
    host, _, port = value.partition(":")
    return host or "127.0.0.1", int(port or 9050)


def _recvall(sock: socket.socket, n: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < n:
        part = sock.recv(n - len(chunks))
        if not part:
            raise NetError("Tor proxy closed the connection")
        chunks += part
    return bytes(chunks)


def socks5_connect(proxy: tuple[str, int], host: str, port: int, timeout: float) -> socket.socket:
    """Open a socket to host:port *through* a SOCKS5 proxy, resolving DNS at the proxy.

    Passing the hostname (not a pre-resolved IP) is what keeps DNS inside Tor.
    """
    try:
        target = host.encode("idna")
    except (UnicodeError, ValueError):
        target = host.encode("ascii", "ignore")
    if not 0 < len(target) <= 255:
        raise NetError(f"invalid hostname '{host}'")

    try:
        sock = socket.create_connection(proxy, timeout)
    except OSError as exc:
        raise NetError(
            f"Tor ni dosegljiv na {proxy[0]}:{proxy[1]} - ali Tor teče? ({exc})"
        ) from exc
    try:
        sock.settimeout(timeout)
        sock.sendall(b"\x05\x01\x00")  # version 5, one method: no authentication
        if _recvall(sock, 2) != b"\x05\x00":
            raise NetError("Tor proxy refused the no-auth handshake")
        sock.sendall(b"\x05\x01\x00\x03" + bytes([len(target)]) + target + port.to_bytes(2, "big"))
        reply = _recvall(sock, 4)
        if reply[1] != 0x00:
            raise NetError(f"Tor proxy could not reach the site (SOCKS error {reply[1]})")
        atyp = reply[3]
        if atyp == 0x01:
            _recvall(sock, 4)
        elif atyp == 0x03:
            _recvall(sock, _recvall(sock, 1)[0])
        elif atyp == 0x04:
            _recvall(sock, 16)
        _recvall(sock, 2)  # bound port
        return sock
    except (OSError, NetError):
        sock.close()
        raise


class _TorHTTPConnection(http.client.HTTPConnection):
    def __init__(self, host, *, proxy, timeout):
        super().__init__(host, timeout=timeout)
        self._proxy = proxy

    def connect(self):
        self.sock = socks5_connect(self._proxy, self.host, self.port, self.timeout)


class _TorHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host, *, proxy, timeout, context):
        super().__init__(host, timeout=timeout, context=context)
        self._proxy = proxy

    def connect(self):
        raw = socks5_connect(self._proxy, self.host, self.port, self.timeout)
        self.sock = self._context.wrap_socket(raw, server_hostname=self.host)


class _TorHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, proxy):
        super().__init__()
        self._proxy = proxy

    def http_open(self, req):
        return self.do_open(functools.partial(_TorHTTPConnection, proxy=self._proxy), req)


class _TorHTTPSHandler(urllib.request.HTTPSHandler):
    def __init__(self, proxy, context):
        super().__init__(context=context)
        self._proxy = proxy

    def https_open(self, req):
        return self.do_open(
            functools.partial(_TorHTTPSConnection, proxy=self._proxy, context=self._context), req
        )


# ---------------------------------------------------------------- SSRF guard

def check_public_url(url: str, resolve: bool = True) -> str:
    """Reject non-http(s) URLs and the human's own local network.

    Over Tor (resolve=False) DNS happens at the exit node, so we only screen literal
    addresses and local-only names; Tor cannot route to the caller's LAN anyway.
    """
    parsed = urllib.parse.urlparse(url.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise NetError("only http(s) URLs are allowed")
    host = parsed.hostname
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        if not address.is_global:
            raise NetError("local and private network addresses are off limits")
        return parsed.geturl()
    low = host.lower()
    if low == "localhost" or low.endswith((".localhost", ".local")):
        raise NetError("local and private network addresses are off limits")
    if resolve:
        try:
            infos = socket.getaddrinfo(host, parsed.port or (443 if parsed.scheme == "https" else 80))
        except socket.gaierror as exc:
            raise NetError(f"cannot resolve {host}") from exc
        for info in infos:
            if not ipaddress.ip_address(info[4][0].split("%")[0]).is_global:
                raise NetError("local and private network addresses are off limits")
    return parsed.geturl()


class _PublicOnlyRedirects(urllib.request.HTTPRedirectHandler):
    def __init__(self, resolve: bool):
        self._resolve = resolve

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_public_url(newurl, self._resolve)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# ---------------------------------------------------------------- Net

def _reachable(proxy: tuple[str, int], timeout: float = 0.6) -> bool:
    try:
        socket.create_connection(proxy, timeout).close()
        return True
    except OSError:
        return False


class Net:
    """Chooses Tor or a direct connection and fetches pages accordingly.

    mode: "on" (fail closed if Tor is down), "off" (direct), "auto" (Tor if reachable).
    """

    def __init__(self, mode: str = "auto", proxy: str = "", timeout: float = HTTP_TIMEOUT):
        self.timeout = timeout
        self.requested = _normalize_mode(mode)
        self.proxy: Optional[tuple[str, int]] = None
        self.tor = False
        self.reason = "neposredno"

        if self.requested == "off":
            self.reason = "izklopljeno (neposredno)"
        elif self.requested == "on":
            self.proxy = _parse_proxy(proxy or "127.0.0.1:9050")
            self.tor = True
            self.reason = f"vsiljen @ {self.proxy[0]}:{self.proxy[1]}"
        else:  # auto
            found = self._find_proxy(proxy)
            if found:
                self.proxy, self.tor = found, True
                self.reason = f"povezan @ {found[0]}:{found[1]}"
            else:
                self.reason = "ni zaznan (iščem neposredno)"

        self._opener = self._make_opener()

    def _find_proxy(self, proxy: str) -> Optional[tuple[str, int]]:
        candidates = [_parse_proxy(proxy)] if proxy else [("127.0.0.1", p) for p in DEFAULT_TOR_PORTS]
        return next((hp for hp in candidates if _reachable(hp)), None)

    def _make_opener(self) -> urllib.request.OpenerDirector:
        handlers: list = [_PublicOnlyRedirects(resolve=not self.tor)]
        if self.tor:
            handlers += [_TorHTTPHandler(self.proxy), _TorHTTPSHandler(self.proxy, ssl.create_default_context())]
        return urllib.request.build_opener(*handlers)

    def fetch(self, url: str, agent: str = USER_AGENT, data: Optional[bytes] = None) -> tuple[str, str]:
        url = check_public_url(url, resolve=not self.tor)
        request = urllib.request.Request(
            url, data=data, headers={"User-Agent": agent, "Accept-Language": "en,sl;q=0.8"}
        )
        with self._opener.open(request, timeout=self.timeout) as response:
            if response.status != 200:
                raise NetError(f"HTTP {response.status}")
            raw = response.read(MAX_PAGE_BYTES)
            charset = response.headers.get_content_charset() or "utf-8"
            return raw.decode(charset, errors="replace"), response.headers.get_content_type()


def _normalize_mode(mode) -> str:
    if mode in (True, "on", "1", "true", "yes", "da"):
        return "on"
    if mode in (False, "off", "0", "false", "no", "ne"):
        return "off"
    return "auto"
