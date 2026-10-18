class AIError(Exception):
    """A question could not be answered.

    ``kind`` says why, so the command can show a translated message that fits;
    ``detail`` is technical text for the log or for an administrator.
    """

    def __init__(self, kind: str, detail: str = "", retry_after: float = 0.0) -> None:
        super().__init__("{}: {}".format(kind, detail) if detail else kind)
        self.kind = kind
        self.detail = detail
        self.retry_after = retry_after
