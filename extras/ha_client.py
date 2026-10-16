"""Minimal Home Assistant WebSocket client (standard library only, plain ws:// as served by http://host:8123).

Used by vito_extras.py to keep Home Assistant schedule helpers and the controller's time programs in sync.
One short lived connection per use:

    with HaClient("http://192.168.176.3:8123", token) as ha:
        configs = ha.call({"type": "schedule/list"})
"""
import base64
import json
import os
import socket
import struct
from urllib.parse import urlparse


class HaError(Exception):
    pass


class HaClient:
    def __init__(self, url, token, timeout=15):
        parsed = urlparse(url)
        if parsed.scheme != "http":
            raise HaError(f"only plain http://host:port is supported, got {url!r}")
        self.host, self.port = parsed.hostname, parsed.port or 80
        self.token, self.timeout = token, timeout
        self.sock, self.buf, self.next_id = None, b"", 1

    # -- context manager ---------------------------------------------------------------------------------------
    def __enter__(self):
        self.sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        try:
            return self._open()
        except BaseException:
            self.__exit__()
            raise

    def _open(self):
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET /api/websocket HTTP/1.1\r\nHost: {self.host}:{self.port}\r\nUpgrade: websocket\r\n"
                           f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            chunk = self.sock.recv(1)
            if not chunk:
                raise HaError("connection closed during the WebSocket handshake")
            head += chunk
        if b" 101 " not in head.split(b"\r\n", 1)[0]:
            raise HaError("WebSocket upgrade refused")
        if self._recv().get("type") != "auth_required":
            raise HaError("unexpected greeting")
        self._send({"type": "auth", "access_token": self.token})
        if self._recv().get("type") != "auth_ok":
            raise HaError("authentication failed (token rejected)")
        return self

    def __exit__(self, *exc):
        try:
            self.sock.close()
        except OSError:
            pass

    # -- frames ------------------------------------------------------------------------------------------------
    def _read(self, n):
        while len(self.buf) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise HaError("connection closed")
            self.buf += chunk
        out, self.buf = self.buf[:n], self.buf[n:]
        return out

    def _recv(self):
        data = b""
        while True:
            b1, b2 = self._read(2)
            length = b2 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read(8))[0]
            data += self._read(length)
            if b1 & 0x80:
                return json.loads(data)

    def _send(self, obj):
        payload = json.dumps(obj).encode()
        mask = os.urandom(4)
        head = bytes([0x81])
        if len(payload) < 126:
            head += bytes([0x80 | len(payload)])
        elif len(payload) < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", len(payload))
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", len(payload))
        self.sock.sendall(head + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))

    # -- API ---------------------------------------------------------------------------------------------------
    def call(self, message):
        """Send one command and return its 'result'; raises HaError if Home Assistant reports a failure."""
        message = dict(message, id=self.next_id)
        self.next_id += 1
        self._send(message)
        while True:
            reply = self._recv()
            if reply.get("id") == message["id"]:
                if not reply.get("success", False):
                    raise HaError(f"{message.get('type')}: {(reply.get('error') or {}).get('message', 'failed')}")
                return reply.get("result")
