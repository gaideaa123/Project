from __future__ import annotations

import socket
import socketserver
import threading

import network_identity
import socks_bridge


def read_exact(sock: socket.socket, count: int) -> bytes:
 data = bytearray()
 while len(data) < count:
  chunk = sock.recv(count - len(data))
  if not chunk:
   raise AssertionError("test SOCKS bağlantısı erken kapandı")
  data.extend(chunk)
 return bytes(data)


class FakeSocksHandler(socketserver.BaseRequestHandler):
 def handle(self) -> None:
  assert read_exact(self.request, 3) == b"\x05\x01\x02"
  self.request.sendall(b"\x05"); self.request.sendall(b"\x02")
  assert read_exact(self.request, 1) == b"\x01"
  user_length = read_exact(self.request, 1)[0]
  username = read_exact(self.request, user_length)
  password_length = read_exact(self.request, 1)[0]
  password = read_exact(self.request, password_length)
  assert username == b"demo-user" and password == b"demo-pass"
  self.request.sendall(b"\x01"); self.request.sendall(b"\x00")
  assert read_exact(self.request, 4) == b"\x05\x01\x00\x03"
  host_length = read_exact(self.request, 1)[0]
  assert read_exact(self.request, host_length) == b"example.com"
  assert read_exact(self.request, 2) == b"\x01\xbb"
  self.request.sendall(b"\x05\x00\x00\x01\x7f\x00\x00\x01\x00\x00")
  assert read_exact(self.request, 4) == b"ping"
  self.request.sendall(b"po"); self.request.sendall(b"ng")


class FakeSocksServer(socketserver.ThreadingTCPServer):
 allow_reuse_address = True
 daemon_threads = True


def expect_invalid(value: str) -> None:
 try:
  network_identity.parse_proxy_line(value)
  raise AssertionError(f"Geçersiz proxy kabul edildi: {value}")
 except network_identity.NetworkIdentityError:
  pass


def main() -> None:
 parsed = network_identity.parse_proxy_line("socks5://demo-user:demo-pass@proxy.example:443")
 assert parsed.server == "socks5://proxy.example:443"
 assert parsed.username == "demo-user" and parsed.password == "demo-pass"
 assert network_identity.proxy_url(parsed).startswith("socks5h://demo-user:demo-pass@")
 encoded = network_identity.parse_proxy_line("socks5://user%40mail:p%40ss@proxy.example:1080")
 assert encoded.username == "user@mail" and encoded.password == "p@ss"
 ipv6 = network_identity.parse_proxy_line("socks5://u:p@[2001:db8::1]:1080")
 assert ipv6.server == "socks5://[2001:db8::1]:1080"
 expect_invalid("socks5://user@proxy.example:1080")
 expect_invalid("socks5://user:pass@proxy.example:1080/path")
 expect_invalid("socks5://user:pass@proxy.example:99999")

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
   assert read_exact(client, 4) == b"pong"
 finally:
  bridge.close(); bridge.close()
  server.shutdown(); server.server_close(); thread.join(timeout=2)

 print("OK: fragmented auth, URL validation, IPv6, relay ve idempotent close doğrulandı")


if __name__ == "__main__":
 main()
