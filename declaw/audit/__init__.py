"""Audit subsystem (Phase 5, DCL-060+).

Typed, versioned audit events + the loggers/sinks that persist them. This is
the durable channel mandated by Inviolable Principle #7 — distinct from the
operational loguru logger (declaw/log.py), which is for developers, not users.
"""
