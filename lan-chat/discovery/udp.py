"""STUB - replace with the real UDP discovery implementation (Member 2).

Keeps the agreed interface so core/app.py runs before the real code exists.
"""


class Discovery:
    def stop(self):
        pass


def start_discovery(name, tcp_port, udp_port, broadcast_addr, get_status, on_event):
    return Discovery()
