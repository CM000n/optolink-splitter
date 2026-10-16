"""Tests of ha_client.py against a tiny WebSocket server that mimics Home Assistant's /api/websocket.
Run:  PYTHONPATH=extras python -m unittest extras/test_ha_client.py
"""
import base64
import hashlib
import json
import socket
import struct
import threading
import unittest

from ha_client import HaClient, HaError

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"


def read_exact(conn, n):
    data = b""
    while len(data) < n:
        chunk = conn.recv(n - len(data))
        if not chunk:
            raise ConnectionError
        data += chunk
    return data


def recv_frame(conn):
    b1, b2 = read_exact(conn, 2)
    length = b2 & 0x7F
    if length == 126:
        length = struct.unpack(">H", read_exact(conn, 2))[0]
    elif length == 127:
        length = struct.unpack(">Q", read_exact(conn, 8))[0]
    mask = read_exact(conn, 4)
    body = bytes(b ^ mask[i % 4] for i, b in enumerate(read_exact(conn, length)))
    return json.loads(body)


def send_frame(conn, obj, fragment=False):
    payload = json.dumps(obj).encode()
    if len(payload) < 126:
        head = bytes([0x81, len(payload)])
    elif len(payload) < 65536:
        head = bytes([0x81, 126]) + struct.pack(">H", len(payload))
    else:
        head = bytes([0x81, 127]) + struct.pack(">Q", len(payload))
    if fragment:                                                   # split into two frames (FIN only on the last one)
        half = len(payload) // 2
        conn.sendall(bytes([0x01, half]) + payload[:half])
        conn.sendall(bytes([0x80, len(payload) - half]) + payload[half:])
    else:
        conn.sendall(head + payload)


class FakeServer(threading.Thread):
    def __init__(self, valid_token="secret"):
        super().__init__(daemon=True)
        self.valid_token = valid_token
        self.sock = socket.socket()
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.received = []
        self.start()

    def close(self):
        self.join(timeout=2)
        self.sock.close()

    def run(self):
        conn, _ = self.sock.accept()
        with conn:
            head = b""
            while b"\r\n\r\n" not in head:
                head += conn.recv(1024)
            key = [line.split(b": ")[1] for line in head.split(b"\r\n") if line.lower().startswith(b"sec-websocket-key")][0]
            accept = base64.b64encode(hashlib.sha1(key + GUID.encode()).digest()).decode()
            conn.sendall(f"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                         f"Sec-WebSocket-Accept: {accept}\r\n\r\n".encode())
            send_frame(conn, {"type": "auth_required"})
            auth = recv_frame(conn)
            if auth.get("access_token") != self.valid_token:
                return send_frame(conn, {"type": "auth_invalid"})
            send_frame(conn, {"type": "auth_ok"})
            try:
                while True:
                    msg = recv_frame(conn)
                    self.received.append(msg)
                    if msg["type"] == "boom":
                        send_frame(conn, {"id": msg["id"], "type": "result", "success": False, "error": {"message": "nope"}})
                    elif msg["type"] == "big":
                        send_frame(conn, {"id": msg["id"], "type": "result", "success": True, "result": ["x" * 100] * 800})
                    else:
                        send_frame(conn, {"id": 99, "type": "event"})                       # unrelated frame is skipped
                        send_frame(conn, {"id": msg["id"], "type": "result", "success": True, "result": {"echo": msg["type"]}},
                                   fragment=True)
            except ConnectionError:
                pass


class HaClientTests(unittest.TestCase):
    def test_call_roundtrip_including_large_and_fragmented_frames(self):
        server = FakeServer()
        self.addCleanup(server.close)
        with HaClient(f"http://127.0.0.1:{server.port}", "secret") as ha:
            self.assertEqual(ha.call({"type": "schedule/list"}), {"echo": "schedule/list"})
            self.assertEqual(len(ha.call({"type": "big"})), 800)
            self.assertEqual(ha.call({"type": "ping", "extra": 1}), {"echo": "ping"})
        self.assertEqual([m["id"] for m in server.received], [1, 2, 3])

    def test_failed_command_raises(self):
        server = FakeServer()
        self.addCleanup(server.close)
        with HaClient(f"http://127.0.0.1:{server.port}", "secret") as ha:
            with self.assertRaisesRegex(HaError, "boom: nope"):
                ha.call({"type": "boom"})

    def test_wrong_token_raises(self):
        server = FakeServer()
        self.addCleanup(server.close)
        with self.assertRaisesRegex(HaError, "authentication failed"):
            with HaClient(f"http://127.0.0.1:{server.port}", "wrong"):
                pass

    def test_https_is_rejected(self):
        with self.assertRaises(HaError):
            HaClient("https://homeassistant.local:8123", "x")


if __name__ == "__main__":
    unittest.main()
