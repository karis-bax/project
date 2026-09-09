"""Backup subsystem: retention policy, age encryption, upload destinations.

Kept out of ``scripts/`` so the pure logic (retention) is unit-testable without
touching the filesystem, a network, or the ``age`` binary.
"""
