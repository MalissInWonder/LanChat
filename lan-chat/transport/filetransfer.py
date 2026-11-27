"""TCP file transfer: dedicated socket per file with progress and temp cleanup."""
import os
import socket
import threading
import time

from transport.protocol import CHUNK_SIZE, clean_filename, encode_file_header

CONNECT_TIMEOUT = 5.0
TRANSFER_TIMEOUT = 30.0
DOWNLOADS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "downloads"
)

_save_lock = threading.Lock()


def send_file(ip, port, path, on_progress=None):
    """Send `path` to `(ip, port)` over a dedicated TCP connection.

    Calls `on_progress(percent)` with integer percentages 0..100.
    Raises FileNotFoundError, ConnectionError, or OSError on failure.
    """
    if not os.path.isfile(path):
        raise FileNotFoundError(f"File not found: {path}")

    size = os.path.getsize(path)
    filename = clean_filename(path)

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(CONNECT_TIMEOUT)
        try:
            sock.connect((ip, port))
        except OSError as exc:
            raise ConnectionError(f"Cannot connect to {ip}:{port}") from exc

        sock.settimeout(TRANSFER_TIMEOUT)
        sock.sendall(encode_file_header(filename, size))

        if size == 0:
            if on_progress is not None:
                on_progress(100)
        else:
            sent = 0
            last_reported = 0
            with open(path, "rb") as f:
                while True:
                    chunk = f.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    sock.sendall(chunk)
                    sent += len(chunk)
                    percent = (sent * 100) // size
                    if on_progress is not None and (
                        percent - last_reported >= 10 or percent == 100
                    ):
                        last_reported = percent
                        on_progress(percent)

        try:
            sock.shutdown(socket.SHUT_WR)
        except OSError:
            pass
    finally:
        try:
            sock.close()
        except OSError:
            pass


def receive_file(sock, sender_ip, filename, size, on_file, on_error):
    """Receive `size` raw bytes from `sock` into `downloads/` safely."""
    safe_name = clean_filename(filename)
    os.makedirs(DOWNLOADS_DIR, exist_ok=True)
    temp_name = f".{safe_name}.{threading.get_ident()}.{time.monotonic_ns()}.part"
    temp_path = os.path.join(DOWNLOADS_DIR, temp_name)

    try:
        sock.settimeout(TRANSFER_TIMEOUT)
        remaining = size
        with open(temp_path, "wb") as out:
            while remaining > 0:
                chunk = sock.recv(min(CHUNK_SIZE, remaining))
                if not chunk:
                    raise ConnectionError("Transfer interrupted before completion")
                out.write(chunk)
                remaining -= len(chunk)

        with _save_lock:
            final_path = _unique_path(DOWNLOADS_DIR, safe_name)
            os.replace(temp_path, final_path)

        if on_file is not None:
            on_file(sender_ip, final_path, size)
    except (OSError, ConnectionError) as exc:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        if on_error is not None:
            on_error(f"Failed to receive '{safe_name}' from {sender_ip}: {exc}")


def _unique_path(directory, filename):
    """Return a non-colliding path in `directory`, adding (1), (2), ... if needed."""
    candidate = os.path.join(directory, filename)
    if not os.path.exists(candidate):
        return candidate

    stem, ext = os.path.splitext(filename)
    counter = 1
    while True:
        candidate = os.path.join(directory, f"{stem}({counter}){ext}")
        if not os.path.exists(candidate):
            return candidate
        counter += 1
