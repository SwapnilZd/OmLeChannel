"""Small, dependency-free validation helpers for generated MP4 artifacts."""
from __future__ import annotations

ELEARNING_VIDEO_WIDTH = 1280
ELEARNING_VIDEO_HEIGHT = 720


class MP4DimensionError(ValueError):
    """Raised when MP4 dimensions are missing, malformed, or unexpected."""


def read_mp4_dimensions(data: bytes) -> tuple[int, int]:
    """Read display dimensions from the first non-empty MP4 ``tkhd`` box."""
    if len(data) < 8 or data[4:8] != b"ftyp":
        raise MP4DimensionError("MP4 is missing its leading ftyp box")

    for box_type, payload_start, box_end in _walk_boxes(data, 0, len(data)):
        if box_type != b"tkhd":
            continue
        if box_end - payload_start < 9:
            raise MP4DimensionError("MP4 tkhd box is too short to contain dimensions")
        width_fixed = int.from_bytes(data[box_end - 8 : box_end - 4], "big")
        height_fixed = int.from_bytes(data[box_end - 4 : box_end], "big")
        width = width_fixed >> 16
        height = height_fixed >> 16
        if width > 0 and height > 0:
            return width, height

    raise MP4DimensionError("MP4 contains no video track dimensions")


def validate_mp4_dimensions(
    data: bytes,
    *,
    expected_width: int,
    expected_height: int,
) -> None:
    """Require an MP4's display dimensions to match the requested canvas."""
    actual = read_mp4_dimensions(data)
    expected = (expected_width, expected_height)
    if actual != expected:
        raise MP4DimensionError(
            f"Video dimensions {actual[0]}x{actual[1]} do not match required "
            f"{expected_width}x{expected_height}"
        )


def _walk_boxes(
    data: bytes,
    start: int,
    end: int,
):
    offset = start
    while offset + 8 <= end:
        size = int.from_bytes(data[offset : offset + 4], "big")
        box_type = data[offset + 4 : offset + 8]
        header_size = 8
        if size == 1:
            if offset + 16 > end:
                raise MP4DimensionError("MP4 has a truncated extended box header")
            size = int.from_bytes(data[offset + 8 : offset + 16], "big")
            header_size = 16
        elif size == 0:
            size = end - offset

        if size < header_size or offset + size > end:
            raise MP4DimensionError(f"MP4 has an invalid {box_type!r} box size")

        payload_start = offset + header_size
        box_end = offset + size
        yield box_type, payload_start, box_end
        if box_type in {b"moov", b"trak"}:
            yield from _walk_boxes(data, payload_start, box_end)
        offset = box_end
