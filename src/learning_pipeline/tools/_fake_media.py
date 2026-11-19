"""Deterministic media placeholders shared by fake production executors."""
from __future__ import annotations


def fake_mp4_bytes(width: int = 1280, height: int = 720) -> bytes:
    """Return a non-playable MP4 structure carrying testable track dimensions."""

    def box(kind: bytes, payload: bytes) -> bytes:
        return (8 + len(payload)).to_bytes(4, "big") + kind + payload

    ftyp = box(b"ftyp", b"mp42")
    tkhd = box(
        b"tkhd",
        b"\x00" * 16
        + (width << 16).to_bytes(4, "big")
        + (height << 16).to_bytes(4, "big"),
    )
    return ftyp + box(b"moov", box(b"trak", tkhd))
