"""Compatibility wrapper for LED helpers."""

from __future__ import annotations

from .tinyuz import TinyUZError, compress_led_payload, generate_rainbow_frames

__all__ = ["TinyUZError", "compress_led_payload", "generate_rainbow_frames"]
