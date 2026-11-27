"""Application-layer framing over TCP streams.

Frames start with a UTF-8 header line terminated by '\\n' (max 512 bytes):
  CHAT|<name>\\n
  MSG|<byte_length>\\n<utf-8 bytes>
  BYE\\n
  FILE|<filename>|<byte_size>\\n<raw bytes>
"""
import os

MAX_HEADER = 512
CHUNK_SIZE = 65536


def clean_filename(filename):
    """Return a safe base filename without path separators, '|', or newlines."""
    normalized = filename.replace("\\", "/")
    name = os.path.basename(normalized)
    for bad in ("|", "\r", "\n", "\x00"):
        name = name.replace(bad, "")
    name = name.strip()
    if not name or name in (".", ".."):
        return "file"
    return name


def read_header(sock):
    """Read one header line byte-by-byte until '\\n'.

    Returns the decoded header string (without '\\r\\n'), or None on clean EOF.
    """
    buf = bytearray()
    while True:
        chunk = sock.recv(1)
        if not chunk:
            if not buf:
                return None
            raise ConnectionError("Connection closed while reading frame header")
        if chunk == b"\n":
            break
        buf.extend(chunk)
        if len(buf) > MAX_HEADER:
            raise ValueError("Frame header exceeds 512 bytes")

    try:
        return buf.decode("utf-8").rstrip("\r")
    except UnicodeDecodeError as exc:
        raise ValueError("Invalid UTF-8 in frame header") from exc


def recv_exact(sock, size):
    """Read exactly `size` bytes from `sock`, looping until complete."""
    if size < 0:
        raise ValueError("Negative byte count")
    if size == 0:
        return b""

    chunks = []
    remaining = size
    while remaining > 0:
        chunk = sock.recv(min(CHUNK_SIZE, remaining))
        if not chunk:
            raise ConnectionError("Connection closed before all data arrived")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def encode_chat(name):
    return f"CHAT|{name}\n".encode("utf-8")


def encode_msg(text):
    payload = text.encode("utf-8")
    header = f"MSG|{len(payload)}\n".encode("utf-8")
    return header + payload


def encode_bye():
    return b"BYE\n"


def encode_file_header(filename, size):
    safe_name = clean_filename(filename)
    return f"FILE|{safe_name}|{size}\n".encode("utf-8")


def parse_header(line):
    """Parse a header line into a tuple describing the frame."""
    if line in ("BYE", "BYE|"):
        return ("BYE",)

    parts = line.split("|")
    kind = parts[0]

    if kind == "CHAT" and len(parts) == 2:
        name = parts[1]
        if not (1 <= len(name) <= 20) or any(ch.isspace() for ch in name):
            raise ValueError("Invalid peer name in CHAT header")
        return ("CHAT", name)

    if kind == "MSG" and len(parts) == 2:
        length_str = parts[1]
        if not (length_str.isascii() and length_str.isdigit()):
            raise ValueError("Invalid byte length in MSG header")
        return ("MSG", int(length_str))

    if kind == "FILE" and len(parts) == 3:
        filename = clean_filename(parts[1])
        size_str = parts[2]
        if not (size_str.isascii() and size_str.isdigit()):
            raise ValueError("Invalid file size in FILE header")
        return ("FILE", filename, int(size_str))

    raise ValueError(f"Unknown or malformed frame header: {line!r}")
