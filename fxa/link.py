"""Client link (experimental): drive a player's character through their own game
client.

The game client is started with `--enable-lua-udp PORT` (see `fx client launch`)
and joins a server whose save has the agent script. Requests go as JSON over UDP
to 127.0.0.1:PORT; the script (lua/agent/link.lua) answers to the port this side
listens on. Nothing here needs RCON, so it works on a server run by someone
else, as long as its save has the script.
"""

import json
import socket
import time


class LinkError(Exception):
    pass


class ClientLink:
    def __init__(self, client_port, timeout=5.0):
        self.client_port = int(client_port)
        self.timeout = timeout
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.bind(("127.0.0.1", 0))
        self.reply_port = self.sock.getsockname()[1]
        self.next_id = int(time.time() * 1000) % 1_000_000

    def close(self):
        self.sock.close()

    def call(self, op, **args):
        self.next_id += 1
        request = {
            "id": self.next_id,
            "op": op,
            "reply_port": self.reply_port,
            **args,
        }
        self.sock.sendto(
            json.dumps(request).encode("utf-8"), ("127.0.0.1", self.client_port)
        )
        deadline = time.time() + self.timeout
        while time.time() < deadline:
            self.sock.settimeout(max(0.05, deadline - time.time()))
            try:
                data, _ = self.sock.recvfrom(65536)
            except socket.timeout:
                break
            try:
                reply = json.loads(data.decode("utf-8"))
            except ValueError:
                continue
            if reply.get("id") == self.next_id:
                if not reply.get("ok"):
                    raise LinkError(reply.get("error") or "request failed")
                return reply
        raise LinkError(
            f"no answer from the game client on UDP port {self.client_port} "
            "(is it running with --enable-lua-udp, connected to a server whose "
            "save has the agent script?)"
        )
