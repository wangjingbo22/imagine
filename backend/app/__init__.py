"""Shared schemas, deterministic planning services, and Agent tool contracts.

This repository splits the ``app`` namespace between the root ``app`` package
and ``backend/app``. Runtime composition intentionally lives in
``app.main:create_app``; the optional Bailian client lives in
``app.infrastructure.bailian``. Importing this package must not create network
clients or read API keys, so this ``__init__`` module has no side effects.
"""
