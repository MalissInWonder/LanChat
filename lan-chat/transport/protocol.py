"""Wire protocol helpers for the LAN chat program.

Every frame starts with a header line terminated by ``\\n`` (maximum 512
bytes).  Chat text and file contents follow the header and are read with
:func:`recv_exact`, because TCP is a byte stream and one ``recv`` call may
return only part of the data.

Frames (QUY_UOC_CHUNG.md, section 5.5)::

    CHAT|<name>\\n
    MSG|<length>\\n + <length> bytes of UTF-8 text
    BYE\\n
    FILE|<filename>|<size>\\n + <size> raw bytes
"""
import os
import socket

MAX_HEADER = 512
MAX_MESSAGE = 1024 * 1024
MAX_NAME = 20
MAX_FILENAME = 150
MAX_FILENAME_BYTES = 200

_INVALID_FILENAME_CHARS = set('<>:"/\\|?*')
_RESERVED_NAMES = {
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
}


class ProtocolError(Exception):
    """A peer sent data that does not follow the protocol."""


def recv_header(sock):
    """Read one header line from *sock* and return it without the newline.

    Reads one byte at a time so the payload that follows stays in the
    socket buffer.  Raises ConnectionError when the peer closes the
    connection and ProtocolError when the header is too long or is not
    valid UTF-8.
    """
    data = bytearray()
    while True:
        chunk = sock.recv(1)
        if not chunk:
            raise ConnectionError("peer closed the connection")
        if chunk == b"\n":
            break
        data.extend(chunk)
        if len(data) > MAX_HEADER:
            raise ProtocolError("header too long")
    try:
        line = data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ProtocolError("header is not valid UTF-8") from exc
    if line.endswith("\r"):
        line = line[:-1]
    return line


def recv_exact(sock, count):
    """Read exactly *count* bytes from *sock*.

    Loops over recv() because one call may return less than requested.
    Raises ConnectionError if the peer closes before enough bytes arrive.
    """
    if count < 0:
        raise ProtocolError("negative byte count")
    chunks = []
    remaining = count
    while remaining > 0:
        chunk = sock.recv(min(remaining, 65536))
        if not chunk:
            raise ConnectionError("peer closed the connection")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def close_quietly(sock):
    """Close a socket from any thread without raising."""
    try:
        sock.shutdown(socket.SHUT_RDWR)
    except OSError:
        pass
    try:
        sock.close()
    except OSError:
        pass


def encode_chat(name):
    """Encode the first frame of an outgoing chat connection."""
    return f"CHAT|{name}\n".encode("utf-8")


def encode_msg(text):
    """Encode one chat message.  The length is counted in UTF-8 bytes."""
    payload = text.encode("utf-8")
    return f"MSG|{len(payload)}\n".encode("utf-8") + payload


def encode_bye():
    """Encode the frame that politely closes a chat."""
    return b"BYE\n"


def encode_file(filename, size):
    """Encode the header of a file transfer connection."""
    return f"FILE|{filename}|{size}\n".encode("utf-8")


def parse_header(line):
    """Split a header line into ``(kind, fields)``.

    ``fields`` depends on the frame type:

    * ``CHAT`` -> ``(name,)``
    * ``MSG``  -> ``(length,)``
    * ``BYE``  -> ``()``
    * ``FILE`` -> ``(filename, size)``

    Raises ProtocolError for an unknown frame or malformed fields.
    """
    parts = line.split("|")
    kind = parts[0]

    if kind == "CHAT":
        if len(parts) != 2:
            raise ProtocolError("malformed CHAT header")
        name = parts[1]
        if not name or len(name) > MAX_NAME:
            raise ProtocolError("invalid peer name")
        if any(ch.isspace() for ch in name):
            raise ProtocolError("invalid peer name")
        return kind, (name,)

    if kind == "MSG":
        if len(parts) != 2:
            raise ProtocolError("malformed MSG header")
        return kind, (_parse_size(parts[1], MAX_MESSAGE),)

    if kind == "BYE":
        if len(parts) != 1:
            raise ProtocolError("malformed BYE header")
        return kind, ()

    if kind == "FILE":
        if len(parts) != 3:
            raise ProtocolError("malformed FILE header")
        return kind, (sanitize_filename(parts[1]), _parse_size(parts[2]))

    raise ProtocolError(f"unknown frame type {kind!r}")


def sanitize_filename(name):
    """Return a safe basename for a file received from a peer.

    Keeps only the last path component, replaces characters that Windows
    cannot use in a file name, and avoids the reserved device names.
    """
    name = str(name).replace("\\", "/")
    name = name.rsplit("/", 1)[-1]

    cleaned = []
    for ch in name:
        if ch in _INVALID_FILENAME_CHARS or ch in "\r\n":
            cleaned.append("_")
        elif ord(ch) < 32 or ord(ch) == 127:
            cleaned.append("_")
        else:
            cleaned.append(ch)
    name = "".join(cleaned).strip().rstrip(". ")

    if not name or name in (".", ".."):
        return "file"

    if len(name) > MAX_FILENAME:
        name = _truncate_filename(name)

    if len(name.encode("utf-8")) > MAX_FILENAME_BYTES:
        name = _truncate_filename_bytes(name)

    name = name.rstrip(". ")
    if not name:
        return "file"

    stem = os.path.splitext(name)[0]
    if stem.upper() in _RESERVED_NAMES:
        name = "_" + name
    return name


def _truncate_filename(name):
    """Shorten a name while keeping its extension."""
    stem, ext = os.path.splitext(name)
    ext = ext[:20]
    return stem[:MAX_FILENAME - len(ext)] + ext


def _truncate_filename_bytes(name):
    """Shorten a name so its UTF-8 form fits in MAX_FILENAME_BYTES."""
    stem, ext = os.path.splitext(name)
    ext = ext[:20]
    budget = MAX_FILENAME_BYTES - len(ext.encode("utf-8"))
    kept = []
    used = 0
    for ch in stem:
        size = len(ch.encode("utf-8"))
        if used + size > budget:
            break
        kept.append(ch)
        used += size
    return "".join(kept) + ext


def _parse_size(text, limit=None):
    """Parse a decimal byte count, rejecting anything unusual."""
    if not text or not text.isascii() or not text.isdigit():
        raise ProtocolError("invalid byte count")
    try:
        value = int(text)
    except ValueError as exc:  # pragma: no cover - isdigit() already checks
        raise ProtocolError("invalid byte count") from exc
    if limit is not None and value > limit:
        raise ProtocolError("byte count too large")
    return value
