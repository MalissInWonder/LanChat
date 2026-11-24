"""Console with a simulated input line.

The last screen line is always the prompt. When a message arrives while the
user is typing, the current line is erased, the message is printed, and the
prompt is redrawn with the text typed so far. Windows only (msvcrt).
"""
import os
import sys
import threading
import time

import msvcrt

PROMPT = "> "
ERASE_LINE = "\r\033[K"


class Console:
    def __init__(self):
        self.screen_lock = threading.Lock()
        self.buffer = ""
        os.system("")  # enables ANSI escape codes in the Windows console

    def write_line(self, text):
        """Print a line from any thread without breaking the input line."""
        with self.screen_lock:
            sys.stdout.write(ERASE_LINE + text + "\n")
            sys.stdout.write(PROMPT + self.buffer)
            sys.stdout.flush()

    def read_line(self):
        """Block until the user presses Enter. Returns the typed text."""
        with self.screen_lock:
            sys.stdout.write(PROMPT + self.buffer)
            sys.stdout.flush()

        while True:
            if not msvcrt.kbhit():
                time.sleep(0.02)
                continue

            ch = msvcrt.getwch()
            if ch in ("\x00", "\xe0"):  # arrow keys and other special keys
                msvcrt.getwch()
                continue

            with self.screen_lock:
                if ch in ("\r", "\n"):
                    line = self.buffer
                    self.buffer = ""
                    sys.stdout.write(ERASE_LINE + PROMPT + line + "\n")
                    sys.stdout.flush()
                    return line
                if ch == "\x03":  # Ctrl+C
                    raise KeyboardInterrupt
                if ch == "\b":
                    self.buffer = self.buffer[:-1]
                elif ch.isprintable():
                    self.buffer += ch
                else:
                    continue
                sys.stdout.write(ERASE_LINE + PROMPT + self.buffer)
                sys.stdout.flush()
