"""Command parsing. Execution lives in core/app.py."""

HELP_LINES = [
    "Commands:",
    "  /list                  show online users",
    "  /chat <name|number>    open a chat with a user",
    "  <text>                 send a message to the current chat partner",
    "  /send <file>           send a file to the current chat partner",
    "  /leave                 close the current chat",
    "  /status <online|away>  change your status",
    "  /help                  show this help",
    "  /quit                  exit the program",
]


def parse_line(line):
    """Split a line into (command, argument).

    Plain text (no leading '/') returns (None, text).
    """
    if not line.startswith("/"):
        return None, line
    parts = line.split(" ", 1)
    command = parts[0].lower()
    argument = parts[1].strip() if len(parts) > 1 else ""
    return command, argument
