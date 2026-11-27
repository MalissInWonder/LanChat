"""TCP server, incoming connection router, and bidirectional chat sessions."""
import socket
import threading

from transport.filetransfer import receive_file
from transport.protocol import (
    encode_bye,
    encode_chat,
    encode_msg,
    parse_header,
    read_header,
    recv_exact,
)

ACCEPT_TIMEOUT = 0.2
CONNECT_TIMEOUT = 5.0
HEADER_TIMEOUT = 10.0


class ChatSession:
    """Thread-safe TCP chat connection with one peer."""

    def __init__(self, sock, on_message=None, on_closed=None):
        self.sock = sock
        self.on_message = on_message
        self.on_closed = on_closed

        self._send_lock = threading.Lock()
        self._state_lock = threading.Lock()
        self._closed = False
        self._closed_by_us = False

    def set_handlers(self, on_message, on_closed):
        self.on_message = on_message
        self.on_closed = on_closed

    def send(self, text):
        """Send one UTF-8 chat message frame. Raises OSError if disconnected."""
        with self._state_lock:
            if self._closed:
                raise OSError("Chat session is closed")
        frame = encode_msg(text)
        with self._send_lock:
            self.sock.sendall(frame)

    def close(self):
        """Send BYE and close the socket cleanly."""
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            self._closed_by_us = True

        try:
            with self._send_lock:
                self.sock.sendall(encode_bye())
        except OSError:
            pass

        self._close_socket()

    def _close_socket(self):
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            self.sock.close()
        except OSError:
            pass

    def _recv_loop(self):
        try:
            while True:
                with self._state_lock:
                    if self._closed:
                        break
                header_line = read_header(self.sock)
                if header_line is None:
                    break
                frame = parse_header(header_line)
                if frame[0] == "BYE":
                    break
                if frame[0] == "MSG":
                    payload = recv_exact(self.sock, frame[1])
                    text = payload.decode("utf-8", errors="replace")
                    if self.on_message is not None:
                        self.on_message(text)
                else:
                    break
        except (OSError, ConnectionError, ValueError):
            pass
        finally:
            with self._state_lock:
                was_local = self._closed_by_us
                self._closed = True
            self._close_socket()
            if not was_local and self.on_closed is not None:
                self.on_closed()


class Server:
    """TCP listener that accepts incoming chat and file connections."""

    def __init__(self, port, on_chat, on_file, on_error):
        self.port = port
        self.on_chat = on_chat
        self.on_file = on_file
        self.on_error = on_error

        self._stop_event = threading.Event()
        self._stopped = False
        self._sessions = set()
        self._sessions_lock = threading.Lock()

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            self.sock.bind(("", self.port))
            self.sock.listen()
            self.sock.settimeout(ACCEPT_TIMEOUT)
        except OSError:
            self.sock.close()
            raise

        self._accept_thread = threading.Thread(
            target=self._accept_loop, name="tcp-acceptor", daemon=True
        )

    def start(self):
        self._accept_thread.start()
        return self

    def stop(self):
        """Stop accepting new connections and close active sessions."""
        if self._stopped:
            return
        self._stopped = True
        self._stop_event.set()

        if (
            self._accept_thread.is_alive()
            and threading.current_thread() is not self._accept_thread
        ):
            self._accept_thread.join(timeout=1.0)

        try:
            self.sock.close()
        except OSError:
            pass

        with self._sessions_lock:
            sessions = list(self._sessions)
            self._sessions.clear()
        for session in sessions:
            session.close()

    def _accept_loop(self):
        while not self._stop_event.is_set():
            try:
                client_sock, addr = self.sock.accept()
            except TimeoutError:
                continue
            except OSError:
                if self._stop_event.is_set():
                    break
                continue

            threading.Thread(
                target=self._handle_client,
                args=(client_sock, addr[0]),
                name="tcp-receiver",
                daemon=True,
            ).start()

    def _handle_client(self, client_sock, sender_ip):
        try:
            client_sock.settimeout(HEADER_TIMEOUT)
            header_line = read_header(client_sock)
            if header_line is None:
                client_sock.close()
                return
            frame = parse_header(header_line)
        except (OSError, ConnectionError, ValueError) as exc:
            try:
                client_sock.close()
            except OSError:
                pass
            if self.on_error is not None:
                self.on_error(f"Invalid incoming TCP connection from {sender_ip}: {exc}")
            return

        if frame[0] == "CHAT":
            peer_name = frame[1]
            client_sock.settimeout(None)
            session = ChatSession(client_sock)
            with self._sessions_lock:
                self._sessions.add(session)
            try:
                if self.on_chat is not None:
                    self.on_chat(peer_name, session)
                session._recv_loop()
            finally:
                with self._sessions_lock:
                    self._sessions.discard(session)
            return

        if frame[0] == "FILE":
            _, filename, size = frame
            try:
                receive_file(
                    client_sock, sender_ip, filename, size, self.on_file, self.on_error
                )
            finally:
                try:
                    client_sock.close()
                except OSError:
                    pass
            return

        try:
            client_sock.close()
        except OSError:
            pass
        if self.on_error is not None:
            self.on_error(f"Unexpected initial frame '{frame[0]}' from {sender_ip}")


def start_server(port, on_chat, on_file, on_error):
    """Start the TCP listener on `port` and return the Server controller."""
    server = Server(port, on_chat, on_file, on_error)
    return server.start()


def open_chat(ip, port, my_name, on_message, on_closed):
    """Connect to `(ip, port)`, send CHAT|<my_name>, and return a ChatSession."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.settimeout(CONNECT_TIMEOUT)
        sock.connect((ip, port))
        sock.sendall(encode_chat(my_name))
        sock.settimeout(None)
    except OSError as exc:
        try:
            sock.close()
        except OSError:
            pass
        raise ConnectionError(f"Cannot connect to {ip}:{port}") from exc

    session = ChatSession(sock, on_message=on_message, on_closed=on_closed)
    threading.Thread(
        target=session._recv_loop, name=f"tcp-chat-{ip}:{port}", daemon=True
    ).start()
    return session
