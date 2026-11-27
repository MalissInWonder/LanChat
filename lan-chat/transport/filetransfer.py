"""File transfer over TCP.

Each file uses its own TCP connection: ``FILE|<filename>|<size>\\n``
followed by exactly ``size`` raw bytes.  The sender is meant to run in its
own thread (core/app.py starts it), and the receiver runs in the
connection thread of the TCP server, so chat is never blocked.
"""
import os
import socket
import time

from transport.protocol import close_quietly, encode_file, sanitize_filename

CHUNK_SIZE = 64 * 1024
CONNECT_TIMEOUT = 5.0
PROGRESS_INTERVAL = 0.1

# Project root is the parent of the transport/ package, so downloads/ is
# always the same folder no matter where the program is started from.
DOWNLOADS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "downloads")


def send_file(ip, port, path, on_progress):
    """Send one file to ``ip:port``.  Blocking; raises OSError on failure.

    ``on_progress(percent)`` is called with 0..100, at most about ten
    times per second (plus the final 100), so the console is not flooded.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"file not found: {path}")

    size = os.path.getsize(path)
    filename = sanitize_filename(os.path.basename(path))

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(CONNECT_TIMEOUT)
    try:
        sock.connect((ip, port))
        sock.settimeout(None)
        sock.sendall(encode_file(filename, size))

        _emit(on_progress, 0)
        sent = 0
        last_percent = 0
        last_time = time.monotonic()
        with open(path, "rb") as handle:
            remaining = size
            while remaining > 0:
                chunk = handle.read(min(CHUNK_SIZE, remaining))
                if not chunk:
                    raise OSError(
                        f"file shrank during transfer: {filename}")
                sock.sendall(chunk)
                remaining -= len(chunk)
                sent += len(chunk)
                percent = int(sent * 100 / size)
                now = time.monotonic()
                if percent > last_percent and (
                        percent >= 100
                        or now - last_time >= PROGRESS_INTERVAL):
                    _emit(on_progress, percent)
                    last_percent = percent
                    last_time = now
        if last_percent < 100:
            _emit(on_progress, 100)
    finally:
        close_quietly(sock)


def receive_file(sock, filename, size, from_ip, on_file, on_error):
    """Receive one file from *sock* into :data:`DOWNLOADS_DIR`.

    Returns the saved path, or None when the transfer failed.  A failed
    transfer removes the partial file and reports the reason through
    ``on_error(message)``.
    """
    filename = sanitize_filename(filename)
    if size < 0:
        _report_error(on_error, f"invalid size for {filename} from {from_ip}")
        return None

    path = None
    try:
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)
        path, handle = _open_unique(DOWNLOADS_DIR, filename)
        received = 0
        try:
            while received < size:
                chunk = sock.recv(min(CHUNK_SIZE, size - received))
                if not chunk:
                    raise ConnectionError(
                        "connection closed during the transfer")
                handle.write(chunk)
                received += len(chunk)
        finally:
            handle.close()
    except OSError as exc:
        if path is not None:
            try:
                os.remove(path)
            except OSError:
                pass
        _report_error(
            on_error,
            f"failed to receive {filename} from {from_ip}: {exc}")
        return None

    if on_file is not None:
        try:
            on_file(from_ip, path, size)
        except Exception:
            pass
    return path


def _open_unique(directory, filename):
    """Create *filename* in *directory*, adding ``(n)`` when it exists."""
    stem, ext = os.path.splitext(filename)
    if not stem:
        stem, ext = filename, ""
    candidate = filename
    counter = 0
    while True:
        path = os.path.join(directory, candidate)
        try:
            return path, open(path, "xb")
        except FileExistsError:
            counter += 1
            candidate = f"{stem} ({counter}){ext}"


def _emit(on_progress, percent):
    if on_progress is None:
        return
    try:
        on_progress(percent)
    except Exception:
        pass


def _report_error(on_error, message):
    if on_error is None:
        return
    try:
        on_error(message)
    except Exception:
        pass
