"""Backwards-compatible ASGI entrypoint.

The application now lives in the modular ``main`` module. This shim re-exports
``app`` so existing tooling/deployment configs that reference ``server:app``
(e.g. ``uvicorn server:app``) continue to work. Prefer ``main:app`` in new code.
"""
from main import app

__all__ = ["app"]
