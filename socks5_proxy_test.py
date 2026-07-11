from __future__ import annotations

import socket
import socketserver
import threading
from unittest.mock import patch

import network_identity
import socks_bridge


class FakeSocksHandler(socketserver.BaseRequestHandler):
 def handle(self) -> None:
  assert self.request.recv(3) == b"\x05\x01\x02"
  self.request.sendall(b"\x05\x02")
  auth = self.request.recv(1024)
  assert auth[0] == 1
  user_length = auth[1]
  username = auth[2:2 + user_length]
  password_length = auth[2 + user_length]
  password = auth[3 + user_length:3 + user_length + password_length]
  assert username == b"demo-user" and password == b"demo-pass"
  self.request.sendall(b"\x01\x00")
  request = self.request.recv(1024)
  assert request[:4] == b"\x05\x01\x00\x03"
  self.request.sendall(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00")
  assert self.request.recv(4) == b"ping"
  self.request.sendall(b"pong")


class FakeSocksServer(socketserver.ThreadingTCPServer):
 allow_reuse_address = True
 daemon_threads = True


def main() -> None:
 parsed = network_identity.parse_proxy_line("socks5://demo-user:demo-pass@proxy.example:443")
 assert parsed.server == "socks5://proxy.example:443"
 assert parsed.username == "demo-user" and parsed.password == "demo-pass"
 assert network_identity.proxy_url(parsed).startswith("socks5h://demo-user:demo-pass@")
 encoded = network_identity.parse_proxy_line("socks5://user%40mail:p%40ss@proxy.example:1080")
 assert encoded.username == "user@mail" and encoded.password == "p@ss"

 server = FakeSocksServer(("127.0.0.1", 0), FakeSocksHandler)
 thread = threading.Thread(target=server.serve_forever, daemon=True); thread.start()
 identity = network_identity.NetworkIdentity(f"socks5://127.0.0.1:{server.server_address[1]}", "demo-user", "demo-pass")
 bridge = socks_bridge.AuthenticatedSocksBridge(identity).start()
 try:
  port = int(bridge.proxy["server"].rsplit(":", 1)[1])
  with socket.create_connection(("127.0.0.1", port), timeout=5) as client:
   client.sendall(b"CONNECT example.com:443 HTTP/1.1\r\nHost: example.com:443\r\n\r\n")
   response = client.recv(1024)
   assert b"200 Connection Established" in response
   client.sendall(b"ping")
   assert client.recv(4) == b"pong"
 finally:
  bridge.close(); server.shutdown(); server.server_close(); thread.join(timeout=2)

 print("OK: URL biçimli kimlik doğrulamalı SOCKS5 ve Chromium CONNECT bridge doğrulandı")


if __name__ == "__main__":
 main()
