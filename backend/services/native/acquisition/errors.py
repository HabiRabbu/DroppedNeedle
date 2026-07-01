"""Shared acquisition control-flow errors.

Lives outside the orchestrator so both the orchestrator and the source strategies can
raise/catch the same type without a circular import.
"""


class OrchestrationError(Exception):
    """Control-flow signal for enqueue/poll/timeout failures. Always caught inside the
    orchestrator; its message is a curated, sanitized string safe to persist/SSE (AUD-11)."""
