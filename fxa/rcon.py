"""Source-RCON client for a Factorio server. Standard library only."""

import itertools
import socket
import struct

AUTH = 3
AUTH_RESPONSE = 2
EXEC = 2
RESPONSE = 0

# A packet is: int32 size, int32 id, int32 type, body, two NUL bytes (all little-endian).
# `size` counts everything after itself, so the smallest valid value is 10.
MIN_PACKET_SIZE = 10
MAX_PACKET_SIZE = 16 * 1024 * 1024


class RconError(Exception):
    pass


class AuthError(RconError):
    pass


def encode_packet(packet_id, packet_type, body):
    payload = body.encode("utf-8") + b"\x00\x00"
    return struct.pack("<iii", 8 + len(payload), packet_id, packet_type) + payload


def _recv_exact(sock, count):
    buf = bytearray()
    while len(buf) < count:
        chunk = sock.recv(count - len(buf))
        if not chunk:
            raise RconError("connection closed by the other side")
        buf += chunk
    return bytes(buf)


def read_packet(sock):
    """Read one packet and return (id, type, body)."""
    (size,) = struct.unpack("<i", _recv_exact(sock, 4))
    if not MIN_PACKET_SIZE <= size <= MAX_PACKET_SIZE:
        raise RconError(f"invalid packet size {size}")
    payload = _recv_exact(sock, size)
    packet_id, packet_type = struct.unpack_from("<ii", payload)
    return packet_id, packet_type, payload[8:-2].decode("utf-8", errors="replace")


class RconClient:
    def __init__(self, host="127.0.0.1", port=27015, password="", timeout=10.0):
        self.host = host
        self.port = port
        self.password = password
        self.timeout = timeout
        self._sock = None
        self._ids = itertools.count(1)

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *exc):
        self.close()

    def connect(self):
        try:
            self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        except OSError as err:
            raise RconError(f"cannot connect to {self.host}:{self.port}: {err}") from err
        auth_id = next(self._ids)
        self._send(auth_id, AUTH, self.password)
        while True:
            packet_id, packet_type, _ = self._read()
            if packet_type == AUTH_RESPONSE:
                break
        if packet_id != auth_id:
            self.close()
            raise AuthError("RCON password rejected")

    def close(self):
        if self._sock is not None:
            self._sock.close()
            self._sock = None

    def command(self, text):
        """Send a console command and return the server's reply."""
        command_id = next(self._ids)
        self._send(command_id, EXEC, text)
        while True:
            packet_id, packet_type, body = self._read()
            if packet_id == command_id and packet_type == RESPONSE:
                return body

    def lua(self, code):
        """Run Lua in the game. The code returns a value by calling rcon.print()."""
        return self.command("/silent-command " + code)

    def _send(self, packet_id, packet_type, body):
        if self._sock is None:
            raise RconError("not connected")
        try:
            self._sock.sendall(encode_packet(packet_id, packet_type, body))
        except OSError as err:
            raise RconError(f"send failed: {err}") from err

    def _read(self):
        if self._sock is None:
            raise RconError("not connected")
        try:
            return read_packet(self._sock)
        except OSError as err:
            raise RconError(f"read failed: {err}") from err
