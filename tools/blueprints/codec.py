"""Blueprint strings: version byte "0", then base64 of zlib of JSON."""

import base64
import json
import zlib

# A string starts with this version byte, which is not part of the base64.
STRING_VERSION = "0"


def game_version(major, minor, patch, build=0):
    """The 64-bit `version` field of a blueprint, for a game version."""
    return (major << 48) | (minor << 32) | (patch << 16) | build


def encode(data):
    """A dict with a `blueprint` or `blueprint_book` key, as a string."""
    text = json.dumps(data, separators=(",", ":"), sort_keys=True)
    packed = zlib.compress(text.encode("utf-8"), 9)
    return STRING_VERSION + base64.b64encode(packed).decode("ascii")


def decode(string):
    """The dict inside a blueprint string."""
    string = string.strip()
    if not string.startswith(STRING_VERSION):
        raise ValueError(f"unknown blueprint version byte {string[:1]!r}")
    packed = base64.b64decode(string[1:], validate=True)
    return json.loads(zlib.decompress(packed).decode("utf-8"))
