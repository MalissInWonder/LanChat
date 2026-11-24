"""Main application: wires discovery, transport and console together."""
import os
import threading

from core.commands import HELP_LINES, parse_line
from core.console import Console
from core.state import State
from discovery.udp import start_discovery
from transport.filetransfer import send_file
from transport.tcp import open_chat, start_server

UDP_PORT = 9999
STATUS_VALUES = ("online", "away")


class App:
    def __init__(self, name, tcp_port, broadcast_addr):
        self.name = name
        self.tcp_port = tcp_port
        self.udp_port = UDP_PORT
        self.broadcast_addr = broadcast_addr
        self.status = "online"

        self.console = Console()
        self.state = State()
        self.sessions = {}                 # peer name -> ChatSession
        self.session_lock = threading.Lock()
        self.current = None                # name of the current chat partner
        self.running = True
        self.discovery = None
        self.server = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def run(self):
        self.console.write_line(
            f"[*] Logged in as {self.name} (TCP {self.tcp_port}, UDP {self.udp_port})")
        self.console.write_line("[*] Type /help for commands")

        try:
            self.discovery = start_discovery(
                self.name, self.tcp_port, self.udp_port, self.broadcast_addr,
                self.get_status, self.on_discovery)
            self.server = start_server(
                self.tcp_port, self.on_chat, self.on_file, self.on_error)
        except OSError as exc:
            self.console.write_line(f"[!] Cannot start network: {exc}")
            return

        try:
            while self.running:
                line = self.console.read_line()
                self.handle_input(line)
        except KeyboardInterrupt:
            pass
        finally:
            self.shutdown()

    def shutdown(self):
        self.running = False
        with self.session_lock:
            sessions = list(self.sessions.values())
            self.sessions.clear()
            self.current = None
        for session in sessions:
            try:
                session.close()
            except OSError:
                pass
        if self.discovery is not None:
            self.discovery.stop()
        if self.server is not None:
            self.server.stop()

    def get_status(self):
        return self.status

    # ------------------------------------------------------------------
    # Input handling
    # ------------------------------------------------------------------

    def handle_input(self, line):
        line = line.strip()
        if not line:
            return

        command, argument = parse_line(line)
        if command is None:
            self.send_text(argument)
            return

        handlers = {
            "/list": self.cmd_list,
            "/chat": self.cmd_chat,
            "/send": self.cmd_send,
            "/leave": self.cmd_leave,
            "/status": self.cmd_status,
            "/help": self.cmd_help,
            "/quit": self.cmd_quit,
        }
        handler = handlers.get(command)
        if handler is None:
            self.console.write_line(f"[!] Unknown command {command}. Type /help.")
            return
        handler(argument)

    def resolve_peer(self, argument):
        """Find a peer by list number or by exact name."""
        peers = self.state.peers()
        if argument.isdigit():
            index = int(argument)
            if 1 <= index <= len(peers):
                return peers[index - 1]
            return None
        for peer in peers:
            if peer.name == argument:
                return peer
        return None

    # ------------------------------------------------------------------
    # Commands
    # ------------------------------------------------------------------

    def cmd_list(self, _argument):
        peers = self.state.peers()
        if not peers:
            self.console.write_line("[*] No other users online")
            return
        self.console.write_line("  #  Name          IP               Status")
        for index, peer in enumerate(peers, start=1):
            self.console.write_line(
                f"  {index}. {peer.name:<12}  {peer.ip:<15}  {peer.status}")

    def cmd_chat(self, argument):
        if not argument:
            self.console.write_line("[!] Usage: /chat <name|number>")
            return

        peer = self.resolve_peer(argument)
        if peer is None:
            self.console.write_line(f"[!] No online user matches '{argument}'")
            return
        if peer.name == self.name:
            self.console.write_line("[!] You cannot chat with yourself")
            return

        name = peer.name
        with self.session_lock:
            session = self.sessions.get(name)

        if session is None:
            try:
                session = open_chat(
                    peer.ip, peer.tcp_port, self.name,
                    on_message=self._message_handler(name),
                    on_closed=self._closed_handler(name))
            except (ConnectionError, OSError):
                self.console.write_line(
                    f"[!] Cannot connect to {name}: the user may be offline")
                return
            with self.session_lock:
                self.sessions[name] = session

        self.current = name
        self.console.write_line(f"[*] Chat with {name} ({peer.ip}:{peer.tcp_port})")
        for line in self.state.pop_unread(name):
            self.console.write_line(line)

    def cmd_send(self, argument):
        if self.current is None:
            self.console.write_line("[!] Open a chat first with /chat")
            return
        if not argument:
            self.console.write_line("[!] Usage: /send <file>")
            return

        path = argument.strip('"')
        if not os.path.isfile(path):
            self.console.write_line(f"[!] File not found: {path}")
            return

        peer = self.state.find_by_name(self.current)
        if peer is None:
            self.console.write_line(f"[!] {self.current} is offline")
            return

        filename = os.path.basename(path)
        threading.Thread(
            target=self._send_file_worker,
            args=(peer, path, filename),
            daemon=True).start()

    def _send_file_worker(self, peer, path, filename):
        last_shown = [-10]

        def on_progress(percent):
            if percent - last_shown[0] >= 10 or percent == 100:
                last_shown[0] = percent
                self.console.write_line(f"[*] Sending {filename} ... {percent}%")

        try:
            send_file(peer.ip, peer.tcp_port, path, on_progress)
            self.console.write_line(f"[*] Sent {filename} to {peer.name}")
        except (OSError, ConnectionError) as exc:
            self.console.write_line(f"[!] Failed to send {filename}: {exc}")

    def cmd_leave(self, _argument):
        if self.current is None:
            self.console.write_line("[!] No chat is open")
            return
        name = self.current
        with self.session_lock:
            session = self.sessions.pop(name, None)
            self.current = None
        if session is not None:
            try:
                session.close()
            except OSError:
                pass
        self.console.write_line(f"[*] Left chat with {name}")

    def cmd_status(self, argument):
        if argument not in STATUS_VALUES:
            self.console.write_line("[!] Usage: /status <online|away>")
            return
        self.status = argument
        self.console.write_line(f"[*] Status set to {argument}")

    def cmd_help(self, _argument):
        for line in HELP_LINES:
            self.console.write_line(line)

    def cmd_quit(self, _argument):
        self.console.write_line("[*] Bye")
        self.running = False

    # ------------------------------------------------------------------
    # Sending and receiving chat text
    # ------------------------------------------------------------------

    def send_text(self, text):
        if self.current is None:
            self.console.write_line("[!] No chat open. Use /chat <name|number>")
            return

        name = self.current
        with self.session_lock:
            session = self.sessions.get(name)
        if session is None:
            self.console.write_line(f"[!] No connection to {name}")
            return

        try:
            session.send(text)
        except OSError:
            self.console.write_line(f"[!] Connection to {name} was lost")
            self._handle_closed(name)
            return

        line = f"[{self.name}] {text}"
        self.state.add_history(name, line)
        self.console.write_line(line)

    def _message_handler(self, name):
        def handler(text):
            self.on_message(name, text)
        return handler

    def _closed_handler(self, name):
        def handler():
            self._handle_closed(name)
        return handler

    def on_message(self, name, text):
        """Called by a TCP receiver thread for each incoming chat message."""
        line = f"[{name}] {text}"
        if self.current == name:
            self.state.add_history(name, line)
            self.console.write_line(line)
        else:
            count = self.state.add_unread(name, line)
            self.console.write_line(f"[*] New message from {name} ({count} unread)")

    def _handle_closed(self, name):
        with self.session_lock:
            existed = self.sessions.pop(name, None) is not None
            if self.current == name:
                self.current = None
        if existed:
            self.console.write_line(f"[*] Chat with {name} has closed")

    # ------------------------------------------------------------------
    # Callbacks from discovery and transport
    # ------------------------------------------------------------------

    def on_discovery(self, kind, peer):
        """kind: "online" | "offline" | "status"."""
        if kind == "online":
            self.state.upsert_peer(peer)
            self.console.write_line(f"[*] {peer.name} is online ({peer.ip})")
        elif kind == "offline":
            removed = self.state.remove_peer(peer.key())
            name = removed.name if removed is not None else peer.name
            self.console.write_line(f"[*] {name} went offline")
        elif kind == "status":
            updated = self.state.set_peer_status(peer.key(), peer.status)
            name = updated.name if updated is not None else peer.name
            self.console.write_line(f"[*] {name} is now {peer.status}")

    def on_chat(self, name, session):
        """A peer opened a chat connection to us."""
        session.set_handlers(self._message_handler(name), self._closed_handler(name))
        with self.session_lock:
            self.sessions[name] = session
        if self.current != name:
            self.console.write_line(
                f"[*] {name} opened a chat with you. Use /chat {name} to reply")

    def on_file(self, from_ip, saved_path, size):
        filename = os.path.basename(saved_path)
        self.console.write_line(
            f"[*] Received {filename} ({size} bytes) from {from_ip}, saved to downloads/")

    def on_error(self, message):
        self.console.write_line(f"[!] {message}")
