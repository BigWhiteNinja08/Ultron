import socket
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from ultron.net import Net, NetError, check_public_url, socks5_connect


class MockSocks5:
    """A tiny SOCKS5 proxy: records the requested hostname and forwards to a local port.

    The hostname never has to exist in DNS - just like Tor, it is resolved at the proxy.
    """

    def __init__(self, routes: dict[str, int]):
        self.routes = routes
        self.requested: list[tuple[str, int]] = []
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen()
        self.port = self.sock.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                client, _ = self.sock.accept()
            except OSError:
                return
            threading.Thread(target=self._handle, args=(client,), daemon=True).start()

    def _handle(self, client):
        with client:
            greeting = client.recv(3)
            if not greeting:  # a bare reachability probe from Net("auto")
                return
            assert greeting == b"\x05\x01\x00"
            client.sendall(b"\x05\x00")
            head = client.recv(4)
            assert head[:2] == b"\x05\x01" and head[3] == 0x03  # CONNECT by domain name
            host = client.recv(client.recv(1)[0]).decode()
            port = int.from_bytes(client.recv(2), "big")
            self.requested.append((host, port))
            if host not in self.routes:
                client.sendall(b"\x05\x04\x00\x01" + bytes(6))  # host unreachable
                return
            upstream = socket.create_connection(("127.0.0.1", self.routes[host]))
            client.sendall(b"\x05\x00\x00\x01" + bytes(6))
            _pipe(client, upstream)

    def close(self):
        self.sock.close()


def _pipe(a, b):
    def forward(src, dst):
        try:
            while data := src.recv(65536):
                dst.sendall(data)
        except OSError:
            pass
        finally:
            try:
                dst.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    t = threading.Thread(target=forward, args=(b, a), daemon=True)
    t.start()
    forward(a, b)
    t.join(5)
    b.close()


@pytest.fixture
def site():
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            body = b"<html><head><title>Onion</title></head><body><p>Hidden hello.</p></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield server.server_address[1]
    server.shutdown()
    server.server_close()


def test_fetch_goes_through_socks5_with_remote_dns(site):
    proxy = MockSocks5({"ultronhidden.onion": site})
    try:
        net = Net("on", f"127.0.0.1:{proxy.port}", timeout=5)
        assert net.tor is True
        body, content_type = net.fetch("http://ultronhidden.onion/")
        assert content_type == "text/html"
        assert "Hidden hello." in body
        assert proxy.requested == [("ultronhidden.onion", 80)]
    finally:
        proxy.close()


def test_open_url_tool_uses_tor_net(site):
    from ultron.tools import run_tool

    proxy = MockSocks5({"ultronhidden.onion": site})
    try:
        net = Net("on", f"127.0.0.1:{proxy.port}", timeout=5)
        out = run_tool("open_url", {"url": "http://ultronhidden.onion/"}, net=net)
        assert out.startswith("Onion\nhttp://ultronhidden.onion/")
        assert "Hidden hello." in out
    finally:
        proxy.close()


def test_socks_error_is_reported(site):
    proxy = MockSocks5({})
    try:
        with pytest.raises(NetError, match="SOCKS error 4"):
            socks5_connect(("127.0.0.1", proxy.port), "nowhere.onion", 80, 5)
    finally:
        proxy.close()


def test_forced_tor_fails_closed_when_tor_is_down():
    net = Net("on", "127.0.0.1:9", timeout=2)  # nothing listens on port 9
    assert net.tor is True
    with pytest.raises(NetError, match="Tor ni dosegljiv"):
        net.fetch("http://example.org/")


def test_auto_mode_detects_tor(site):
    proxy = MockSocks5({})
    try:
        assert Net("auto", f"127.0.0.1:{proxy.port}").tor is True
    finally:
        proxy.close()
    assert Net("auto", "127.0.0.1:9").tor is False
    assert Net("off").tor is False


@pytest.mark.parametrize("url", ["http://127.0.0.1/", "http://localhost:11434/", "http://10.0.0.5/", "http://printer.local/"])
def test_tor_mode_still_blocks_local_addresses(url):
    with pytest.raises(NetError, match="off limits"):
        check_public_url(url, resolve=False)


def test_tor_mode_allows_onion_and_names_without_local_dns():
    assert check_public_url("http://duckduckgogg42xjoc72x3sjasowoarfbgcmvfimaftt6twagswzczad.onion/", resolve=False)
    assert check_public_url("https://does-not-exist-in-dns.example/", resolve=False)
