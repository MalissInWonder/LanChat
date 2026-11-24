"""Plain data classes shared by the core modules."""
import time


class Peer:
    """A user seen on the LAN through UDP discovery."""

    def __init__(self, name, ip, tcp_port, status="online", last_seen=None):
        self.name = name
        self.ip = ip
        self.tcp_port = tcp_port
        self.status = status  # "online" or "away"
        self.last_seen = last_seen if last_seen is not None else time.monotonic()

    def key(self):
        """A peer is identified by (IP, TCP port)."""
        return (self.ip, self.tcp_port)

    def __repr__(self):
        return f"Peer({self.name!r}, {self.ip!r}, {self.tcp_port}, {self.status!r})"
