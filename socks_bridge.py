from __future__ import annotations

"""Local HTTP CONNECT bridge for authenticated upstream SOCKS5 proxies."""

import select
import socket
import socketserver
import struct
import threading
from dataclasses import dataclass
from urllib.parse import urlparse

import network_identity

class SocksBridgeError(RuntimeError):
 pass

def _read_exact(sock: socket.socket, count: int) -> bytes:
 data = bytearray()
 while len(data) < count:
  chunk = sock.recv(count - len(data))
  if not chunk:
   raise SocksBridgeError("SOCKS5 bağlantısı beklenmedik biçimde kapandı")
  data.extend(chunk)
 return bytes(data)

def _read_headers(sock: socket.socket, limit: int = 65536) -> bytes:
 data = bytearray()
 while b"\r\n\r\n" not in data:
  chunk = sock.recv(4096)
  if not chunk:
   break
  data.extend(chunk)
  if len(data) > limit:
   raise SocksBridgeError("CONNECT başlığı çok büyük")
 return bytes(data)

def _target(value: str) -> tuple[str, int]:
 value = value.strip()
 if value.startswith("["):
  end = value.find("]")
  if end < 0 or end + 2 > len(value):
   raise SocksBridgeError("CONNECT hedefi geçersiz")
  return value[1:end], int(value[end + 2:])
 host, separator, port = value.rpartition(":")
 if not separator or not host or not port.isdigit():
  raise SocksBridgeError("CONNECT hedefi host:port olmalı")
 return host, int(port)

def _consume_address(sock: socket.socket, atyp: int) -> None:
 if atyp == 1:
  _read_exact(sock, 4)
 elif atyp == 4:
  _read_exact(sock, 16)
 elif atyp == 3:
  _read_exact(sock, _read_exact(sock, 1)[0])
 else:
  raise SocksBridgeError("SOCKS5 adres türü geçersiz")
 _read_exact(sock, 2)

def _connect_upstream(identity: network_identity.NetworkIdentity, host: str, port: int) -> socket.socket:
 parsed = urlparse(identity.server)
 upstream = socket.create_connection((parsed.hostname, parsed.port), timeout=20)
 upstream.settimeout(20)
 try:
  methods = b"\x02" if identity.username else b"\x00"
  upstream.sendall(b"\x05\x01" + methods)
  version, method = _read_exact(upstream, 2)
  if version != 5 or method == 255:
   raise SocksBridgeError("SOCKS5 kimlik doğrulama yöntemi reddedildi")
  if method == 2:
   username = identity.username.encode("utf-8"); password = identity.password.encode("utf-8")
   if not username or not password or len(username) > 255 or len(password) > 255:
    raise SocksBridgeError("SOCKS5 kullanıcı adı/parola uzunluğu geçersiz")
   upstream.sendall(b"\x01" + bytes([len(username)]) + username + bytes([len(password)]) + password)
   auth_version, status = _read_exact(upstream, 2)
   if auth_version != 1 or status != 0:
    raise SocksBridgeError("SOCKS5 kullanıcı adı veya parola reddedildi")
  elif method != 0:
   raise SocksBridgeError("SOCKS5 proxy desteklenmeyen kimlik doğrulama istedi")
  encoded_host = host.encode("idna")
  if len(encoded_host) > 255:
   raise SocksBridgeError("SOCKS5 hedef alan adı çok uzun")
  upstream.sendall(b"\x05\x01\x00\x03" + bytes([len(encoded_host)]) + encoded_host + struct.pack("!H", port))
  version, reply, _, atyp = _read_exact(upstream, 4)
  if version != 5 or reply != 0:
   raise SocksBridgeError(f"SOCKS5 hedef bağlantısı reddedildi (kod {reply})")
  _consume_address(upstream, atyp)
  upstream.settimeout(None)
  return upstream
 except Exception:
  upstream.close()
  raise

def _relay(left: socket.socket, right: socket.socket) -> None:
 sockets = [left, right]
 while True:
  readable, _, _ = select.select(sockets, [], [], 60)
  if not readable:
   continue
  for source in readable:
   data = source.recv(65536)
   if not data:
    return
   (right if source is left else left).sendall(data)

@dataclass
class AuthenticatedSocksBridge:
 identity: network_identity.NetworkIdentity

 def __post_init__(self) -> None:
  self.identity.validate()
  if urlparse(self.identity.server).scheme.casefold() != "socks5":
   raise SocksBridgeError("Bridge yalnız SOCKS5 için kullanılabilir")
  bridge = self

  class Handler(socketserver.BaseRequestHandler):
   def handle(self) -> None:
    upstream = None
    try:
     headers = _read_headers(self.request)
     first = headers.split(b"\r\n", 1)[0].decode("latin-1", "replace")
     method, destination, _ = first.split(" ", 2)
     if method.upper() != "CONNECT":
      self.request.sendall(b"HTTP/1.1 405 Method Not Allowed\r\nConnection: close\r\n\r\n")
      return
     host, port = _target(destination)
     upstream = _connect_upstream(bridge.identity, host, port)
     self.request.sendall(b"HTTP/1.1 200 Connection Established\r\n\r\n")
     _relay(self.request, upstream)
    except Exception:
     try:
      self.request.sendall(b"HTTP/1.1 502 Bad Gateway\r\nConnection: close\r\n\r\n")
     except Exception:
      pass
    finally:
     if upstream is not None:
      upstream.close()

  class Server(socketserver.ThreadingTCPServer):
   allow_reuse_address = True
   daemon_threads = True

  self._server = Server(("127.0.0.1", 0), Handler)
  self._thread = threading.Thread(target=self._server.serve_forever, name="socks5-connect-bridge", daemon=True)

 @property
 def proxy(self) -> dict[str, str]:
  return {"server": f"http://127.0.0.1:{self._server.server_address[1]}"}

 def start(self) -> "AuthenticatedSocksBridge":
  self._thread.start()
  return self

 def close(self) -> None:
  self._server.shutdown()
  self._server.server_close()
  if self._thread.is_alive() and self._thread is not threading.current_thread():
   self._thread.join(timeout=2)
