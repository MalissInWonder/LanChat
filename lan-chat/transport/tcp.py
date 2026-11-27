"""TCP chat transport.

The listener accepts one connection per chat or per file.  Each accepted
connection gets its own thread; the first frame decides whether the
connection is a chat (``CHAT``) or a file transfer (``FILE``).

Incoming chats are handed to the application through
``on_chat(name, session)``.  The application registers its handlers with
``session.set_handlers(on_message, on_closed)``; the server starts the
receiver thread right after ``on_chat`` returns so no message is lost.
"""
import socket
import threading

from transport.filetransfer import receive_file
from transport.protocol import (
    ProtocolError,
    close_quietly,
    encode_bye,
    encode_chat,
    encode_msg,
    parse_header,
    recv_exact,
    recv_header,
)

CONNECT_TIMEOUT = 5.0
HANDSHAKE_TIMEOUT = 10.0
ACCEPT_BACKLOG = 50
JOIN_TIMEOUT = 1.0


class ChatSession:
    """One open chat connection.

    ``on_message(text)`` is called for every incoming message.
    ``on_closed()`` is called exactly once when the peer closes the
    connection; a local :meth:`close` does not call it because the
    application already knows that it closed the chat.
    """

    def __init__(self, sock, name=None, peer_ip=None, peer_port=None,
                 on_error=None, on_finished=None):
        self.sock = sock
        self.name = name
        self.peer_ip = peer_ip
        self.peer_port = peer_port
        self.on_message = None
        self.on_closed = None
        self.on_error = on_error
        self.on_finished = on_finished
        self.closed = False
        self._started = False
        self._thread = None
        self._send_lock = threading.Lock()
        self._state_lock = threading.Lock()

    # -- setup ---------------------------------------------------------

    def set_handlers(self, on_message, on_closed):
        """Register the callbacks for incoming messages and remote close."""
        with self._state_lock:
            self.on_message = on_message
            self.on_closed = on_closed
            ready = self._started and self._thread is None and not self.closed
        if ready:
            self._spawn_receiver()

    def start(self):
        """Start the receiver thread (once handlers are available)."""
        with self._state_lock:
            self._started = True
            ready = (self._thread is None and not self.closed
                     and self.on_message is not None)
        if ready:
            self._spawn_receiver()

    def _spawn_receiver(self):
        with self._state_lock:
            if self._thread is not None or self.closed:
                return
            thread = threading.Thread(
                target=self._receive_loop, name="chat-recv", daemon=True)
            self._thread = thread
        thread.start()

    # -- public operations ---------------------------------------------

    def send(self, text):
        """Send one chat message.  Raises OSError when the link is broken."""
        frame = encode_msg(text)
        with self._send_lock:
            if self.closed:
                raise OSError("chat connection is closed")
            try:
                self.sock.sendall(frame)
            except OSError:
                self._mark_closed()
                raise

    def close(self):
        """Send BYE and close the socket.  Safe to call more than once."""
        with self._state_lock:
            if self.closed:
                return
            self.closed = True
        with self._send_lock:
            try:
                self.sock.sendall(encode_bye())
            except OSError:
                pass
        close_quietly(self.sock)

    # -- internals -----------------------------------------------------

    def _mark_closed(self):
        with self._state_lock:
            already = self.closed
            self.closed = True
        if not already:
            close_quietly(self.sock)

    def _report_error(self, message):
        if self.on_error is None:
            return
        try:
            self.on_error(message)
        except Exception:
            pass

    def _receive_loop(self):
        try:
            while True:
                header = recv_header(self.sock)
                kind, fields = parse_header(header)
                if kind == "MSG":
                    payload = recv_exact(self.sock, fields[0])
                    text = payload.decode("utf-8", "replace")
                    handler = self.on_message
                    if handler is not None:
                        try:
                            handler(text)
                        except Exception:
                            pass
                elif kind == "BYE":
                    break
                else:
                    raise ProtocolError(
                        f"unexpected {kind} frame on a chat connection")
        except ProtocolError as exc:
            self._report_error(
                f"chat with {self.name or self.peer_ip}: {exc}")
        except OSError:
            pass
        finally:
            with self._state_lock:
                local_close = self.closed
                self.closed = True
                handler = self.on_closed
            close_quietly(self.sock)
            if not local_close and handler is not None:
                try:
                    handler()
                except Exception:
                    pass
            if self.on_finished is not None:
                try:
                    self.on_finished(self)
                except Exception:
                    pass


class Server:
    """TCP listener for incoming chats and file transfers."""

    def __init__(self, port, on_chat, on_file, on_error):
        self.port = port
        self.on_chat = on_chat
        self.on_file = on_file
        self.on_error = on_error
        self._lock = threading.Lock()
        self._sockets = set()
        self._sessions = set()
        self._listener = None
        self._thread = None
        self._stopped = False

    def start(self):
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            listener.bind(("", self.port))
            listener.listen(ACCEPT_BACKLOG)
        except OSError:
            close_quietly(listener)
            raise
        self._listener = listener
        self._thread = threading.Thread(
            target=self._accept_loop, name="tcp-accept", daemon=True)
        self._thread.start()

    def stop(self):
        """Stop accepting and close every socket owned by this server."""
        with self._lock:
            if self._stopped:
                return
            self._stopped = True
            listener = self._listener
            self._listener = None
            sockets = list(self._sockets)
            self._sockets.clear()
            sessions = list(self._sessions)
            self._sessions.clear()
        if listener is not None:
            close_quietly(listener)
        for sock in sockets:
            close_quietly(sock)
        for session in sessions:
            session.close()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=JOIN_TIMEOUT)

    # -- accept loop ---------------------------------------------------

    def _accept_loop(self):
        while True:
            listener = self._listener
            if listener is None:
                break
            try:
                conn, addr = listener.accept()
            except OSError:
                break
            with self._lock:
                if self._stopped:
                    close_quietly(conn)
                    break
                self._sockets.add(conn)
            try:
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except OSError:
                pass
            threading.Thread(
                target=self._handle_connection,
                args=(conn, addr),
                name="tcp-conn",
                daemon=True).start()

    def _handle_connection(self, conn, addr):
        ip = addr[0]
        handed_off = False
        try:
            conn.settimeout(HANDSHAKE_TIMEOUT)
            header = recv_header(conn)
            kind, fields = parse_header(header)
            conn.settimeout(None)

            if kind == "CHAT":
                name = fields[0]
                session = ChatSession(
                    conn, name=name, peer_ip=ip, peer_port=addr[1],
                    on_error=self._report_error,
                    on_finished=self._discard_session)
                self._replace_session(session)
                handed_off = True
                try:
                    self.on_chat(name, session)
                except Exception as exc:
                    self._report_error(
                        f"cannot handle chat from {name}: {exc}")
                    self._discard_session(session)
                    session.close()
                    return
                session.start()

            elif kind == "FILE":
                filename, size = fields
                receive_file(conn, filename, size, ip,
                             self.on_file, self._report_error)

            else:
                raise ProtocolError(f"unexpected {kind} frame")

        except ProtocolError as exc:
            self._report_error(f"bad connection from {ip}: {exc}")
        except OSError:
            pass
        finally:
            with self._lock:
                self._sockets.discard(conn)
            if not handed_off:
                close_quietly(conn)

    def _replace_session(self, session):
        """Drop an older incoming chat from the same peer name."""
        with self._lock:
            previous = [s for s in self._sessions if s.name == session.name]
            self._sessions.add(session)
        for old in previous:
            old.close()
            self._discard_session(old)

    def _discard_session(self, session):
        with self._lock:
            self._sessions.discard(session)

    def _report_error(self, message):
        if self.on_error is None:
            return
        try:
            self.on_error(message)
        except Exception:
            pass


def start_server(port, on_chat, on_file, on_error):
    """Bind the TCP port and start accepting connections.

    ``on_chat(name, session)``, ``on_file(from_ip, saved_path, size)`` and
    ``on_error(message)`` are called from worker threads.
    """
    server = Server(port, on_chat, on_file, on_error)
    server.start()
    return server


def open_chat(ip, port, my_name, on_message, on_closed):
    """Connect to a peer and return a started :class:`ChatSession`.

    Raises ConnectionError when the peer cannot be reached.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(CONNECT_TIMEOUT)
    try:
        sock.connect((ip, port))
        sock.settimeout(None)
        try:
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass
        sock.sendall(encode_chat(my_name))
    except OSError as exc:
        close_quietly(sock)
        raise ConnectionError(
            f"cannot connect to {ip}:{port}: {exc}") from exc

    session = ChatSession(sock, peer_ip=ip, peer_port=port)
    session.set_handlers(on_message, on_closed)
    session.start()
    return session
