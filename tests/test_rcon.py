import socket
import threading
import time
import unittest

from fxa.rcon import (
    AUTH,
    AUTH_RESPONSE,
    EXEC,
    RESPONSE,
    AuthError,
    RconClient,
    RconError,
    encode_packet,
    read_packet,
)


class FakeServer:
    """One-connection RCON server.

    `handler(body)` returns a str to send as a normal reply, or bytes to send
    raw before dropping the connection. `chunk` splits every send into pieces
    of that many bytes to imitate TCP fragmentation.
    """

    def __init__(self, password="secret", handler=lambda body: body, chunk=None):
        self.password = password
        self.handler = handler
        self.chunk = chunk
        self.listener = socket.create_server(("127.0.0.1", 0))
        self.port = self.listener.getsockname()[1]
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()

    def close(self):
        self.listener.close()
        self.thread.join(timeout=2)

    def _send(self, conn, data):
        if self.chunk is None:
            conn.sendall(data)
            return
        for start in range(0, len(data), self.chunk):
            conn.sendall(data[start : start + self.chunk])
            time.sleep(0.001)

    def _serve(self):
        try:
            conn, _ = self.listener.accept()
        except OSError:
            return
        with conn:
            while True:
                try:
                    packet_id, packet_type, body = read_packet(conn)
                except (RconError, OSError):
                    return
                if packet_type == AUTH:
                    reply_id = packet_id if body == self.password else -1
                    self._send(conn, encode_packet(reply_id, AUTH_RESPONSE, ""))
                elif packet_type == EXEC:
                    reply = self.handler(body)
                    if isinstance(reply, bytes):
                        self._send(conn, reply)
                        return
                    self._send(conn, encode_packet(packet_id, RESPONSE, reply))


class PacketTest(unittest.TestCase):
    def test_encode_matches_wire_format(self):
        self.assertEqual(
            encode_packet(7, EXEC, "hi"),
            b"\x0c\x00\x00\x00" b"\x07\x00\x00\x00" b"\x02\x00\x00\x00" b"hi\x00\x00",
        )

    def test_empty_body_has_minimum_size(self):
        self.assertEqual(encode_packet(1, RESPONSE, "")[:4], b"\x0a\x00\x00\x00")

    def test_negative_id_round_trips(self):
        left, right = socket.socketpair()
        with left, right:
            left.sendall(encode_packet(-1, AUTH_RESPONSE, ""))
            self.assertEqual(read_packet(right), (-1, AUTH_RESPONSE, ""))

    def test_rejects_bad_size(self):
        left, right = socket.socketpair()
        with left, right:
            left.sendall(b"\x02\x00\x00\x00" + b"\x00" * 8)
            with self.assertRaises(RconError):
                read_packet(right)


class ClientTest(unittest.TestCase):
    def serve(self, **kwargs):
        server = FakeServer(**kwargs)
        self.addCleanup(server.close)
        return server

    def test_command_round_trip(self):
        server = self.serve()
        with RconClient(port=server.port, password="secret") as client:
            self.assertEqual(client.command("/version"), "/version")
            self.assertEqual(client.command("again"), "again")

    def test_lua_uses_silent_command(self):
        server = self.serve()
        with RconClient(port=server.port, password="secret") as client:
            self.assertEqual(client.lua("rcon.print(1)"), "/silent-command rcon.print(1)")

    def test_wrong_password(self):
        server = self.serve()
        with self.assertRaises(AuthError):
            RconClient(port=server.port, password="nope").connect()

    def test_large_reply(self):
        big = "x" * 200_000
        server = self.serve(handler=lambda body: big)
        with RconClient(port=server.port, password="secret") as client:
            self.assertEqual(client.command("observe"), big)

    def test_fragmented_reply(self):
        server = self.serve(handler=lambda body: "y" * 500, chunk=7)
        with RconClient(port=server.port, password="secret") as client:
            self.assertEqual(client.command("observe"), "y" * 500)

    def test_unicode_body(self):
        server = self.serve()
        with RconClient(port=server.port, password="secret") as client:
            self.assertEqual(client.command("железо ⚙"), "железо ⚙")

    def test_connection_dropped_mid_packet(self):
        truncated = encode_packet(2, RESPONSE, "partial")[:-5]
        server = self.serve(handler=lambda body: truncated)
        with RconClient(port=server.port, password="secret") as client:
            with self.assertRaises(RconError):
                client.command("observe")

    def test_no_reply_times_out(self):
        release = threading.Event()
        self.addCleanup(release.set)

        def stall(body):
            release.wait(timeout=5)
            return b""

        server = self.serve(handler=stall)
        with RconClient(port=server.port, password="secret", timeout=0.2) as client:
            with self.assertRaises(RconError):
                client.command("observe")

    def test_nothing_listening(self):
        with socket.create_server(("127.0.0.1", 0)) as probe:
            free_port = probe.getsockname()[1]
        with self.assertRaises(RconError):
            RconClient(port=free_port).connect()

    def test_command_before_connect(self):
        with self.assertRaises(RconError):
            RconClient().command("x")


if __name__ == "__main__":
    unittest.main()
