"""An asynchronous media receipt pauses the parent without consuming model calls."""


class WaitingForMedia(Exception):
    def __init__(self, result):
        self.result = result


class WaitingForDependencies(Exception):
    """A confirmed plan yields its worker while production children run."""


class WaitingForStoryConfirmation(Exception):
    """Story rechecks stop at a human decision, without keeping a worker alive."""

    def __init__(self, result):
        self.result = result
