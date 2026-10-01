"""The exceptions of the DuoForge package."""


class DuoforgeLibraryError(RuntimeError):
    """The shared library is missing, does not load, or has another version.

    The message names every path tried and what was found there.
    """


class DuoforgeError(RuntimeError):
    """A DuoForge call returned a status other than DUOFORGE_OK.

    status_name is the C name (duoforge_status_name), for example
    "DUOFORGE_E_STALE_EPOCH". statuses holds the per-environment statuses of
    a batch call, or None for a single call.
    """

    def __init__(self, status_name, statuses=None):
        self.status_name = status_name
        self.statuses = statuses
        detail = status_name
        if statuses is not None:
            failed = [int(i) for i in (statuses != 0).nonzero()[0]]
            detail = f"{status_name} (environments {failed[:16]}{'...' if len(failed) > 16 else ''})"
        super().__init__(detail)
