"""Shared state protected by a single lock.

Chat histories and unread counters are keyed by the peer's name.
"""
import threading


class State:
    def __init__(self):
        self.lock = threading.Lock()
        self._peers = {}     # (ip, tcp_port) -> Peer
        self._history = {}   # name -> list of display lines
        self._unread = {}    # name -> number of unread incoming messages

    # --- online peers -------------------------------------------------

    def upsert_peer(self, peer):
        with self.lock:
            self._peers[peer.key()] = peer

    def remove_peer(self, key):
        with self.lock:
            return self._peers.pop(key, None)

    def set_peer_status(self, key, status):
        with self.lock:
            peer = self._peers.get(key)
            if peer is not None:
                peer.status = status
            return peer

    def peers(self):
        """Online peers sorted by name. Numbering in /list uses this order."""
        with self.lock:
            return sorted(self._peers.values(), key=lambda p: p.name.lower())

    def find_by_name(self, name):
        with self.lock:
            for peer in self._peers.values():
                if peer.name == name:
                    return peer
            return None

    # --- chat history and unread --------------------------------------

    def add_history(self, name, line):
        with self.lock:
            self._history.setdefault(name, []).append(line)

    def add_unread(self, name, line):
        """Store an incoming line for a chat that is not open. Returns the unread count."""
        with self.lock:
            self._history.setdefault(name, []).append(line)
            self._unread[name] = self._unread.get(name, 0) + 1
            return self._unread[name]

    def pop_unread(self, name):
        """Return the unread lines for this peer and reset the counter."""
        with self.lock:
            count = self._unread.get(name, 0)
            self._unread[name] = 0
            if count == 0:
                return []
            return self._history.get(name, [])[-count:]
