"""Entry point for the LAN chat program.

Usage:
    python lanchat.py --name Quan --port 5000
"""
import argparse
import re
import sys
import socket
from core.app import App

NAME_PATTERN = re.compile(r"^[^\s|]{1,20}$")
MIN_PYTHON = (3, 14)




def detect_broadcast():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))  # không gửi dữ liệu, chỉ để Windows chọn card đi ra
        ip = s.getsockname()[0]
    finally:
        s.close()
    parts = ip.split(".")
    return ".".join(parts[:3] + ["255"])
    
def parse_args(argv=None):
    parser = argparse.ArgumentParser(description="LAN chat and file sharing")
    parser.add_argument("--name", required=True, help="your display name")
    parser.add_argument("--port", type=int, default=5000, help="TCP port for chat and files")
    parser.add_argument("--broadcast", default=detect_broadcast(),
                        help="broadcast address (use 127.255.255.255 for same-PC testing)")
    return parser.parse_args(argv)


def main(argv=None):
    if sys.version_info < MIN_PYTHON:
        print("Python 3.14 or newer is required.")
        return 1

    args = parse_args(argv)

    if not NAME_PATTERN.match(args.name):
        print("Name must be 1-20 characters, with no spaces or '|'.")
        return 1
    if not 1 <= args.port <= 65535:
        print("Port must be between 1 and 65535.")
        return 1

    app = App(name=args.name, tcp_port=args.port, broadcast_addr=args.broadcast)
    app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
