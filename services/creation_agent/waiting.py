"""An asynchronous media receipt pauses the parent without consuming model calls."""


class WaitingForMedia(Exception):
    def __init__(self, result):
        self.result = result
