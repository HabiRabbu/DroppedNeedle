"""Pure decision specs — one per file, source-agnostic.

Each spec is ``(candidate, target, context, policy) -> Decision`` with NO I/O.
The ordered pipeline that runs them lives in ``..pipeline``.
"""
