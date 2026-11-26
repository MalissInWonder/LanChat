"""UDP discovery and status broadcasting (Member 2).

Periodically broadcasts HELLO|<name>|<tcp_port>|<status> over UDP and listens
for peer announcements to detect online, status change, and offline events.
"""
import socket
import threading
import time

from core.models import Peer

BROADCAST_INTERVAL = 3.0
CHECK_INTERVAL = 1.0
PEER_TIMEOUT = 10.0
POLL_INTERVAL = 0.1
SOCKET_TIMEOUT = 0.2
BUFFER_SIZE = 1024
VALID_STATUSES = ("online", "away")


class Discovery:
    """Manages UDP broadcast and peer timeout threads."""

    def __init__(self, name, tcp_port, udp_port, broadcast_addr, get_status, on_event):
        self.name = name
        self.tcp_port = tcp_port
        self.udp_port = udp_port
        self.broadcast_addr = broadcast_addr
        self.get_status = get_status
        self.on_event = on_event

        self._peers = {}  # (ip, tcp_port) -> Peer
        self._stop_event = threading.Event()
        self._stopped = False

        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
            if hasattr(socket, "SIO_UDP_CONNRESET"):
                self.sock.ioctl(socket.SIO_UDP_CONNRESET, False)
            self.sock.settimeout(SOCKET_TIMEOUT)
            self.sock.bind(("", self.udp_port))
        except OSError:
            self.sock.close()
            raise

        self._broadcast_thread = threading.Thread(
            target=self._broadcast_loop, name="udp-broadcaster", daemon=True
        )
        self._listen_thread = threading.Thread(
            target=self._listen_loop, name="udp-listener", daemon=True
        )

    def start(self):
        self._broadcast_thread.start()
        self._listen_thread.start()
        return self

    def stop(self):
        """Stop background threads cleanly and close the UDP socket."""
        if self._stopped:
            return
        self._stopped = True
        self._stop_event.set()

        current = threading.current_thread()
        if self._broadcast_thread.is_alive() and current is not self._broadcast_thread:
            self._broadcast_thread.join(timeout=1.0)
        if self._listen_thread.is_alive() and current is not self._listen_thread:
            self._listen_thread.join(timeout=1.0)

        try:
            self.sock.close()
        except OSError:
            pass

    def send_hello(self, status=None):
        """Send a HELLO broadcast packet immediately."""
        if self._stop_event.is_set():
            return
        if status not in VALID_STATUSES:
            status = self.get_status()
            if status not in VALID_STATUSES:
                status = "online"

        payload = f"HELLO|{self.name}|{self.tcp_port}|{status}".encode("utf-8")
        try:
            self.sock.sendto(payload, (self.broadcast_addr, self.udp_port))
        except OSError:
            pass

    def _broadcast_loop(self):
        last_sent = 0.0
        last_status = None

        while not self._stop_event.is_set():
            status = self.get_status()
            now = time.monotonic()
            if status != last_status or (now - last_sent) >= BROADCAST_INTERVAL:
                self.send_hello(status)
                last_status = status
                last_sent = now
            self._stop_event.wait(POLL_INTERVAL)

    def _listen_loop(self):
        last_check = time.monotonic()

        while not self._stop_event.is_set():
            try:
                data, addr = self.sock.recvfrom(BUFFER_SIZE)
                self._handle_packet(data, addr[0])
            except TimeoutError:
                pass
            except ConnectionResetError:
                pass
            except OSError:
                if self._stop_event.is_set():
                    break

            now = time.monotonic()
            if (now - last_check) >= CHECK_INTERVAL:
                self._check_timeouts(now)
                last_check = now

    def _handle_packet(self, data, sender_ip):
        parsed = parse_hello(data)
        if parsed is None:
            return

        peer_name, peer_port, status = parsed
        if peer_name == self.name and peer_port == self.tcp_port:
            return

        now = time.monotonic()
        key = (sender_ip, peer_port)
        existing = self._peers.get(key)

        if existing is None:
            peer = Peer(peer_name, sender_ip, peer_port, status, now)
            self._peers[key] = peer
            self.on_event("online", _copy_peer(peer))
            return

        if existing.name != peer_name:
            self.on_event("offline", _copy_peer(existing))
            peer = Peer(peer_name, sender_ip, peer_port, status, now)
            self._peers[key] = peer
            self.on_event("online", _copy_peer(peer))
            return

        existing.last_seen = now
        if existing.status != status:
            existing.status = status
            self.on_event("status", _copy_peer(existing))

    def _check_timeouts(self, now):
        expired_keys = [
            key for key, peer in self._peers.items()
            if (now - peer.last_seen) >= PEER_TIMEOUT
        ]
        for key in expired_keys:
            peer = self._peers.pop(key)
            self.on_event("offline", _copy_peer(peer))


def parse_hello(data):
    """Parse b'HELLO|<name>|<tcp_port>|<status>'. Returns tuple or None."""
    try:
        text = data.decode("utf-8").strip("\r\n")
    except UnicodeDecodeError:
        return None

    parts = text.split("|")
    if len(parts) != 4 or parts[0] != "HELLO":
        return None

    name, port_str, status = parts[1], parts[2], parts[3]
    if not (1 <= len(name) <= 20) or any(ch.isspace() for ch in name):
        return None
    if not (port_str.isascii() and port_str.isdigit()):
        return None

    tcp_port = int(port_str)
    if not (1 <= tcp_port <= 65535):
        return None
    if status not in VALID_STATUSES:
        return None

    return name, tcp_port, status


def _copy_peer(peer):
    return Peer(peer.name, peer.ip, peer.tcp_port, peer.status, peer.last_seen)


def start_discovery(name, tcp_port, udp_port, broadcast_addr, get_status, on_event):
    """Start UDP discovery threads and return the Discovery controller."""
    discovery = Discovery(name, tcp_port, udp_port, broadcast_addr, get_status, on_event)
    return discovery.start()
