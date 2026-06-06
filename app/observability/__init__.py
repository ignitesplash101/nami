"""Operational observability: request context, structured logging, metering.

These modules are deliberately dependency-light (stdlib logging + contextvars).
Every best-effort write (metering events, audit entries) is wrapped in
`contextlib.suppress` by the caller so observability never fails a user request.
"""
