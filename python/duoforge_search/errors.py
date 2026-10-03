"""The search's own refusal (spec section 7): a decision it cannot make
correctly stops the run and says why, never falls back."""


class SearchError(RuntimeError):
    """A search refusal: a missed certificate, a table it cannot read, a
    leaf the encoder refused."""
