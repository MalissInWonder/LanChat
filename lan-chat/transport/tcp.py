"""STUB - replace with the real TCP transport implementation (Member 3).

Interface change: ChatSession has set_handlers(on_message, on_closed) so that
sessions created by the acceptor (incoming chats) can also deliver messages.
"""


class Server:
    def stop(self):
        pass


class ChatSession:
    def __init__(self):
        self.on_message = None
        self.on_closed = None

    def set_handlers(self, on_message, on_closed):
        self.on_message = on_message
        self.on_closed = on_closed

    def send(self, text):
        raise OSError("stub: chat not implemented")

    def close(self):
        pass


def start_server(port, on_chat, on_file, on_error):
    return Server()


def open_chat(ip, port, my_name, on_message, on_closed):
    raise ConnectionError("stub: chat not implemented")
