"""Acquisition decision pipeline (ArrRebuild).

Inspired by Lidarr's ``DecisionEngine/Specifications`` but fixing its structural
warts: every spec is a PURE function ``(candidate, target, context, policy) ->
Decision`` (no I/O, no mocks), all external state is hoisted into one immutable
``DecisionContext`` built by ``build_context``, and rejections are typed
(``RejectCode`` + ``Disposition``) so they drive failover/blocklist/retry
directly. One framework, both sources (Soulseek + Usenet).

See ``.dev-notes/ArrRebuild/architecture.md`` for the blueprint and migration order.
"""
