"""LAN peer-to-peer chat and file sharing application.

UDP is used for discovery/status and TCP is used for framed chat/file data.
"""

from __future__ import annotations

import argparse
import json
import msvcrt
import os
import queue
import socket
import sys
import threading
import time
from pathlib import Path
from typing import Dict, Optional, Tuple


DISCOVERY_PORT = 9999
DISCOVERY_INTERVAL = 3
PEER_TIMEOUT = 10
BUFFER_SIZE = 64 * 1024
DOWNLOAD_DIR = Path("downloads")


class LanChat:
    def __init__(self, name: str, port: int, broadcast: str) -> None:
        self.name = name
        self.port = port
        self.broadcast = broadcast
        self.status = "online"
        self.running = True
        self.lock = threading.RLock()
        self.output_lock = threading.Lock()
        self.peers: Dict[str, dict] = {}
        self.connections: Dict[str, socket.socket] = {}
        self.histories: Dict[str, list[str]] = {}
        self.unread: Dict[str, int] = {}
        self.current_partner: Optional[str] = None
        self.events: "queue.Queue[str]" = queue.Queue()
        self.input_buffer = ""
        self.input_active = False
        self.tcp_server: Optional[socket.socket] = None
        DOWNLOAD_DIR.mkdir(exist_ok=True)

    def print_line(self, text: str = "") -> None:
        with self.output_lock:
            suffix = f"\n> {self.input_buffer}" if self.input_active else ""
            print(f"\r\033[K{text}{suffix}", end="", flush=True)

    def notify(self, text: str) -> None:
        self.print_line(f"[*] {text}")

    @staticmethod
    def _read_exact(sock: socket.socket, size: int) -> bytes:
        data = bytearray()
        while len(data) < size:
            chunk = sock.recv(min(BUFFER_SIZE, size - len(data)))
            if not chunk:
                raise ConnectionError("peer closed the connection")
            data.extend(chunk)
        return bytes(data)

    @classmethod
    def _read_frame(cls, sock: socket.socket) -> Tuple[str, bytes]:
        header = bytearray()
        while not header or not header.endswith(b"\n"):
            chunk = sock.recv(1)
            if not chunk:
                raise ConnectionError("peer closed the connection")
            header.extend(chunk)
            if len(header) > 256:
                raise ValueError("invalid frame header")
        parts = header[:-1].decode("ascii").split("|")
        if len(parts) != 2 or not parts[1].isdigit():
            raise ValueError("invalid frame header")
        return parts[0], cls._read_exact(sock, int(parts[1]))

    @staticmethod
    def _send_frame(sock: socket.socket, kind: str, payload: bytes) -> None:
        header = f"{kind}|{len(payload)}\n".encode("ascii")
        sock.sendall(header + payload)

    def _presence(self) -> bytes:
        return f"HELLO|{self.name}|{self.port}|{self.status}".encode("utf-8")

    def udp_broadcaster(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            while self.running:
                try:
                    sock.sendto(self._presence(), (self.broadcast, DISCOVERY_PORT))
                except OSError:
                    pass
                time.sleep(DISCOVERY_INTERVAL)
        finally:
            sock.close()

    def udp_listener(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(("", DISCOVERY_PORT))
        except OSError as exc:
            self.notify(f"Cannot bind UDP port {DISCOVERY_PORT}: {exc}")
            sock.close()
            return
        sock.settimeout(1)
        try:
            while self.running:
                try:
                    data, address = sock.recvfrom(1024)
                    fields = data.decode("utf-8").split("|")
                    if len(fields) != 4 or fields[0] != "HELLO":
                        continue
                    peer_name, peer_port, status = fields[1], int(fields[2]), fields[3]
                    if peer_name == self.name:
                        continue
                    with self.lock:
                        first_seen = peer_name not in self.peers
                        self.peers[peer_name] = {
                            "ip": address[0],
                            "port": peer_port,
                            "status": status,
                            "last_seen": time.monotonic(),
                        }
                    if first_seen:
                        self.notify(f"{peer_name} is online ({address[0]}:{peer_port})")
                except socket.timeout:
                    pass
                except (ValueError, UnicodeDecodeError):
                    continue
                self._remove_expired_peers()
        finally:
            sock.close()

    def _remove_expired_peers(self) -> None:
        now = time.monotonic()
        with self.lock:
            expired = [
                name for name, peer in self.peers.items()
                if now - peer["last_seen"] > PEER_TIMEOUT
            ]
            for name in expired:
                del self.peers[name]
        for name in expired:
            self.notify(f"{name} went offline")

    def tcp_acceptor(self) -> None:
        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("", self.port))
        server.listen()
        server.settimeout(1)
        self.tcp_server = server
        self.notify(f"Listening on TCP port {self.port}")
        try:
            while self.running:
                try:
                    client, address = server.accept()
                    threading.Thread(
                        target=self._receive_connection,
                        args=(client, address, False),
                        daemon=True,
                    ).start()
                except socket.timeout:
                    continue
        finally:
            server.close()

    def _receive_connection(
        self, conn: socket.socket, address: tuple, outgoing: bool
    ) -> None:
        peer_name: Optional[str] = None
        try:
            if outgoing:
                self._send_frame(conn, "HELLO", json.dumps({
                    "name": self.name, "port": self.port
                }).encode("utf-8"))
            kind, payload = self._read_frame(conn)
            if kind != "HELLO":
                raise ValueError("connection did not start with HELLO")
            hello = json.loads(payload.decode("utf-8"))
            peer_name = str(hello["name"])
            if peer_name == self.name:
                raise ValueError("self-connection")
            with self.lock:
                old = self.connections.get(peer_name)
                self.connections[peer_name] = conn
            if old is not None and old is not conn:
                old.close()
            self.histories.setdefault(peer_name, [])
            if not outgoing:
                self._send_frame(conn, "HELLO", json.dumps({
                    "name": self.name, "port": self.port
                }).encode("utf-8"))
            with self.lock:
                self.connections[peer_name] = conn
            self.notify(f"Connected to {peer_name}")
            while self.running:
                kind, payload = self._read_frame(conn)
                if kind == "MSG":
                    message = payload.decode("utf-8")
                    self._handle_message(peer_name, message)
                elif kind == "FILE":
                    self._receive_file(conn, peer_name, payload)
                elif kind == "BYE":
                    break
                else:
                    raise ValueError(f"unknown frame type: {kind}")
        except (ConnectionError, OSError):
            if peer_name:
                self.notify(f"{peer_name} disconnected")
        except (ValueError, KeyError, json.JSONDecodeError) as exc:
            self.notify(f"Invalid data from peer: {exc}")
        finally:
            if peer_name:
                with self.lock:
                    if self.connections.get(peer_name) is conn:
                        del self.connections[peer_name]
            try:
                conn.close()
            except OSError:
                pass

    def _handle_message(self, peer_name: str, message: str) -> None:
        with self.lock:
            self.histories.setdefault(peer_name, []).append(f"[{peer_name}] {message}")
            if peer_name != self.current_partner:
                self.unread[peer_name] = self.unread.get(peer_name, 0) + 1
                unread = self.unread[peer_name]
            else:
                unread = 0
        if unread:
            self.notify(f"New message from {peer_name} ({unread} unread)")
        else:
            self.print_line(f"[{peer_name}] {message}")

    def _receive_file(self, conn: socket.socket, peer_name: str, payload: bytes) -> None:
        if len(payload) < 8:
            raise ValueError("invalid file frame")
        filename_length = int.from_bytes(payload[:4], "big")
        size = int.from_bytes(payload[4:8], "big")
        filename = payload[8:8 + filename_length].decode("utf-8")
        if len(payload) != 8 + filename_length:
            raise ValueError("invalid file metadata")
        safe_name = Path(filename).name
        target = DOWNLOAD_DIR / safe_name
        temp = target.with_suffix(target.suffix + ".part")
        received = 0
        try:
            with temp.open("wb") as file:
                while received < size:
                    chunk = conn.recv(min(BUFFER_SIZE, size - received))
                    if not chunk:
                        raise ConnectionError("file transfer interrupted")
                    file.write(chunk)
                    received += len(chunk)
                    if size:
                        self.print_line(f"[*] Receiving {safe_name}: {received * 100 // size}%")
            temp.replace(target)
            self.notify(f"Received {safe_name} from {peer_name} -> {target}")
        except (OSError, ConnectionError):
            try:
                temp.unlink()
            except FileNotFoundError:
                pass
            raise

    def connect(self, peer_name: str) -> bool:
        with self.lock:
            peer = self.peers.get(peer_name)
        if not peer:
            self.notify(f"Peer not found or offline: {peer_name}")
            return False
        try:
            conn = socket.create_connection((peer["ip"], peer["port"]), timeout=5)
            conn.settimeout(None)
            with self.lock:
                self.connections[peer_name] = conn
            threading.Thread(
                target=self._receive_connection,
                args=(conn, (peer["ip"], peer["port"]), True),
                daemon=True,
            ).start()
            with self.lock:
                self.current_partner = peer_name
                self.unread[peer_name] = 0
            return True
        except OSError as exc:
            self.notify(f"Cannot connect to {peer_name}: {exc}")
            return False

    def send_message(self, message: str) -> None:
        with self.lock:
            partner = self.current_partner
            conn = self.connections.get(partner) if partner else None
        if not partner or conn is None:
            self.notify("Open a chat first with /chat <name|number>")
            return
        try:
            self._send_frame(conn, "MSG", message.encode("utf-8"))
            with self.lock:
                self.histories.setdefault(partner, []).append(f"[{self.name}] {message}")
            self.print_line(f"[{self.name}] {message}")
        except OSError:
            self.notify(f"Could not send message to {partner}")

    def send_file(self, path_text: str) -> None:
        with self.lock:
            partner = self.current_partner
            conn = self.connections.get(partner) if partner else None
        path = Path(path_text.strip().strip('"'))
        if not path.is_file():
            self.notify(f"File not found: {path}")
            return
        if not partner or conn is None:
            self.notify("Open a chat first with /chat <name|number>")
            return
        threading.Thread(
            target=self._send_file_worker, args=(conn, partner, path), daemon=True
        ).start()

    def _send_file_worker(self, conn: socket.socket, partner: str, path: Path) -> None:
        try:
            name = path.name.encode("utf-8")
            size = path.stat().st_size
            metadata = len(name).to_bytes(4, "big") + size.to_bytes(4, "big") + name
            self._send_frame(conn, "FILE", metadata)
            sent = 0
            with path.open("rb") as file:
                while chunk := file.read(BUFFER_SIZE):
                    conn.sendall(chunk)
                    sent += len(chunk)
                    self.print_line(f"[*] Sending {path.name}: {sent * 100 // size if size else 100}%")
            self.notify(f"Sent {path.name} to {partner}")
        except (OSError, ValueError) as exc:
            self.notify(f"File transfer failed: {exc}")

    def list_peers(self) -> None:
        self._remove_expired_peers()
        with self.lock:
            peers = sorted(self.peers.items())
        if not peers:
            self.notify("No online peers found")
            return
        for index, (name, peer) in enumerate(peers, 1):
            self.print_line(f"{index}. {name} ({peer['ip']}:{peer['port']}) {peer['status']}")

    def choose_peer(self, value: str) -> Optional[str]:
        with self.lock:
            peers = sorted(self.peers)
        if value.isdigit() and 1 <= int(value) <= len(peers):
            return peers[int(value) - 1]
        return value if value in peers else None

    def show_help(self) -> None:
        self.print_line("Commands: /list, /chat <name|number>, /send <file>, /leave,")
        self.print_line("/status <online|away>, /help, /quit. Other text sends a message.")

    def leave(self) -> None:
        with self.lock:
            partner = self.current_partner
            conn = self.connections.get(partner) if partner else None
            self.current_partner = None
        if conn:
            try:
                self._send_frame(conn, "BYE", b"")
                conn.close()
            except OSError:
                pass
        if partner:
            self.notify(f"Left chat with {partner}")

    def command_loop(self) -> None:
        self.show_help()
        while self.running:
            try:
                line = self._read_command().strip()
            except (EOFError, KeyboardInterrupt):
                line = "/quit"
            if not line:
                continue
            if not line.startswith("/"):
                self.send_message(line)
                continue
            command, _, argument = line.partition(" ")
            command = command.lower()
            if command == "/list":
                self.list_peers()
            elif command == "/chat":
                peer = self.choose_peer(argument.strip())
                if peer and self.connect(peer):
                    self.notify(f"Chatting with {peer}")
                    with self.lock:
                        for message in self.histories.get(peer, []):
                            self.print_line(message)
                        self.unread[peer] = 0
                else:
                    self.notify("Usage: /chat <name|number>")
            elif command == "/send":
                self.send_file(argument)
            elif command == "/leave":
                self.leave()
            elif command == "/status" and argument.strip() in {"online", "away"}:
                self.status = argument.strip()
                self.notify(f"Status changed to {self.status}")
            elif command == "/help":
                self.show_help()
            elif command == "/quit":
                self.running = False
            else:
                self.notify("Invalid command. Use /help.")

    def _read_command(self) -> str:
        """Read a line while allowing receiver threads to redraw the prompt."""
        if not sys.stdin.isatty():
            return input("> ")
        self.input_buffer = ""
        self.input_active = True
        with self.output_lock:
            print("> ", end="", flush=True)
        try:
            while True:
                char = msvcrt.getwch()
                if char in ("\r", "\n"):
                    with self.output_lock:
                        print()
                    return self.input_buffer
                if char == "\003":
                    raise KeyboardInterrupt
                if char == "\b":
                    if self.input_buffer:
                        self.input_buffer = self.input_buffer[:-1]
                        with self.output_lock:
                            print("\b \b", end="", flush=True)
                    continue
                if char in ("\x00", "\xe0"):
                    msvcrt.getwch()
                    continue
                self.input_buffer += char
                with self.output_lock:
                    print(char, end="", flush=True)
        finally:
            self.input_active = False

    def run(self) -> None:
        threads = [
            threading.Thread(target=self.udp_broadcaster, daemon=True),
            threading.Thread(target=self.udp_listener, daemon=True),
            threading.Thread(target=self.tcp_acceptor, daemon=True),
        ]
        for thread in threads:
            thread.start()
        try:
            self.command_loop()
        finally:
            self.running = False
            self.leave()
            if self.tcp_server:
                self.tcp_server.close()
            self.notify("Goodbye")


def main() -> None:
    parser = argparse.ArgumentParser(description="LAN Chat & File Sharing")
    parser.add_argument("--name", required=True, help="Your display name")
    parser.add_argument("--port", type=int, default=0, help="TCP port (0 selects a free port)")
    parser.add_argument(
        "--broadcast", default="255.255.255.255",
        help="Broadcast address, e.g. 127.255.255.255 for local testing",
    )
    args = parser.parse_args()
    if not 1 <= args.port <= 65535 and args.port != 0:
        parser.error("--port must be between 1 and 65535")
    # Port 0 is useful for selecting a free local port before discovery starts.
    if args.port == 0:
        probe = socket.socket()
        probe.bind(("", 0))
        args.port = probe.getsockname()[1]
        probe.close()
    print(f"Starting LAN Chat as {args.name} (TCP {args.port}, UDP {DISCOVERY_PORT})")
    LanChat(args.name, args.port, args.broadcast).run()


if __name__ == "__main__":
    main()
