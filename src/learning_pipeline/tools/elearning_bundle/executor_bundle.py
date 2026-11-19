"""RealElearningBundleAssemblerExecutor — deterministic, no LLM.

Reads the intermediate CourseContent JSON from ArtifactStore, replaces every
VideoSlotScreen with a VideoPlayerScreen, stages all adjacent assets, renders
final HTML, generates an asset manifest, and produces a deterministic ZIP bundle.

No LLM, Manim, HeyGen, or any provider call is made in this executor.
"""
from __future__ import annotations

import hashlib
import io
import json
import posixpath
import re
import zipfile
from typing import Any

from learning_pipeline.media_validation import (
    ELEARNING_VIDEO_HEIGHT,
    ELEARNING_VIDEO_WIDTH,
    MP4DimensionError,
    validate_mp4_dimensions,
)
from learning_pipeline.runtime.artifact_store import ArtifactStore
from learning_pipeline.runtime.execution import ExecutionContext
from learning_pipeline.tools.elearning_bundle._captions import (
    CaptionConversionError,
    ensure_vtt,
)
from learning_pipeline.tools.elearning_bundle.contracts import (
    BundleAssetRef,
    ElearningBundleAssemblyInput,
    ElearningBundleAssemblyOutput,
    VideoInsertion,
    VideoSlotRequirement,
)
from learning_pipeline.tools.elearning_bundle.slot_validator import (
    CourseSlotValidator,
    SlotPreservationError,
)
from learning_pipeline.tools.errors import InvalidToolInputError, InvalidToolOutputError

# Reserved output filenames that the assembler writes — assets must not collide with these.
_RESERVED_NAMES = frozenset({"index.html", "course.course.json", "asset-manifest.json"})

# Characters not safe in bundle filenames derived from slot IDs or artifact names.
_UNSAFE_CHARS_RE = re.compile(r"[^\w\-.]")

# Fixed ZIP timestamp for reproducibility: (year, month, day, hour, minute, second)
_ZIP_TIMESTAMP = (2020, 1, 1, 0, 0, 0)


class AssemblyError(RuntimeError):
    """Raised when a deterministic assembly step fails."""


def _safe_bundle_name(raw: str, suffix: str) -> str:
    """Derive a safe, deterministic bundle filename from slot_id + suffix.

    Examples:
        ("avatar-introduction", ".mp4") -> "avatar-introduction.mp4"
        ("concept animation!", ".vtt")  -> "concept_animation_.vtt"
    """
    stem = _UNSAFE_CHARS_RE.sub("_", raw)
    return f"{stem}{suffix}"


def _assert_safe_bundle_path(logical_path: str, reserved: frozenset[str]) -> None:
    """Raise AssemblyError for any dangerous path component."""
    if not logical_path.strip():
        raise AssemblyError("Bundle path must not be blank")
    if posixpath.isabs(logical_path):
        raise AssemblyError(f"Absolute bundle path rejected: {logical_path!r}")
    parts = logical_path.replace("\\", "/").split("/")
    for part in parts:
        if part == "..":
            raise AssemblyError(f"Path traversal rejected: {logical_path!r}")
        if not part and logical_path != "./":
            raise AssemblyError(f"Empty path component in: {logical_path!r}")
    filename = parts[-1].lower()
    if filename in reserved:
        raise AssemblyError(
            f"Bundle path {logical_path!r} collides with a reserved output filename"
        )


def _build_asset_manifest(
    entry_html: str,
    course_json: str,
    assets: list[tuple[str, bytes, str]],  # (path, data, media_type)
) -> bytes:
    """Build a machine-readable asset manifest as JSON bytes."""
    asset_entries = [
        {
            "path": path,
            "media_type": media_type,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
        }
        for path, data, media_type in sorted(assets, key=lambda x: x[0])
    ]
    manifest = {
        "entry_html": entry_html,
        "course_json": course_json,
        "assets": asset_entries,
    }
    return json.dumps(manifest, indent=2, sort_keys=True).encode("utf-8")


def _build_deterministic_zip(
    files: list[tuple[str, bytes]],
) -> bytes:
    """Build a deterministic ZIP from (relative_path, data) pairs.

    Uses fixed timestamps and sorted file order for reproducibility.
    """
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for rel_path, data in sorted(files, key=lambda x: x[0]):
            info = zipfile.ZipInfo(rel_path, date_time=_ZIP_TIMESTAMP)
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, data)
    return buf.getvalue()


def _validate_mp4_for_slide(data: bytes) -> None:
    """Require a valid MP4 matching the e-learning slide canvas."""
    if len(data) < 8 or data[4:8] != b"ftyp":
        raise AssemblyError(
            f"Video artifact does not appear to be a valid MP4 (missing ftyp box); "
            f"got header {data[:8]!r}"
        )
    try:
        validate_mp4_dimensions(
            data,
            expected_width=ELEARNING_VIDEO_WIDTH,
            expected_height=ELEARNING_VIDEO_HEIGHT,
        )
    except MP4DimensionError as exc:
        raise AssemblyError(
            f"Video artifact does not match the slide canvas: {exc}"
        ) from exc


class RealElearningBundleAssemblerExecutor:
    """Real deterministic executor for elearning.bundle.assemble.

    Parameters
    ----------
    artifact_store:
        Store for reading inputs and publishing outputs.  Required.
    """

    def __init__(self, *, artifact_store: ArtifactStore) -> None:
        self._store = artifact_store

    async def execute(self, context: ExecutionContext) -> dict[str, Any]:
        # ── 1. Validate input contract ─────────────────────────────────────────
        try:
            inp = ElearningBundleAssemblyInput.model_validate(context.inputs)
        except Exception as exc:
            raise InvalidToolInputError(
                f"[{context.task_id}] Invalid elearning.bundle.assemble input: {exc}"
            ) from exc

        wf_id = context.workflow_id
        ns = f"elearning-bundle/{wf_id}"

        # ── 2. Read intermediate course JSON ───────────────────────────────────
        try:
            course_bytes = await self._store.get_bytes(inp.course_json_uri)
        except Exception as exc:
            raise AssemblyError(
                f"Cannot read course JSON from {inp.course_json_uri!r}: {exc}"
            ) from exc

        try:
            course_dict = json.loads(course_bytes)
        except json.JSONDecodeError as exc:
            raise AssemblyError(f"Intermediate course JSON is not valid JSON: {exc}") from exc

        # ── 3. Defensive slot validation ───────────────────────────────────────
        required_ids = tuple(s.slot_id for s in inp.required_slots)
        validator = CourseSlotValidator()
        report = validator.validate(course_dict, required_ids)
        if not report.valid:
            raise SlotPreservationError(report)

        # Verify every insertion targets an existing slot
        discovered_set = set(report.discovered_slot_ids)
        for vi in inp.video_insertions:
            if vi.slot_id not in discovered_set:
                raise AssemblyError(
                    f"VideoInsertion slot_id {vi.slot_id!r} does not match any "
                    f"VideoSlotScreen in the course JSON"
                )

        # Verify required slots with required=True have exactly one insertion
        insertion_slot_ids = {vi.slot_id for vi in inp.video_insertions}
        for req in inp.required_slots:
            if req.required and req.slot_id not in insertion_slot_ids:
                raise AssemblyError(
                    f"Required slot {req.slot_id!r} has no VideoInsertion"
                )

        # Required captions are part of the delivery contract, not advisory metadata.
        req_by_id = {r.slot_id: r for r in inp.required_slots}
        missing_captions_slots: list[str] = [
            vi.slot_id
            for vi in inp.video_insertions
            if req_by_id.get(vi.slot_id)
            and req_by_id[vi.slot_id].captions_required
            and vi.captions_uri is None
        ]
        if missing_captions_slots:
            raise AssemblyError(
                "Required captions are missing for video slot(s): "
                + ", ".join(sorted(missing_captions_slots))
            )

        # ── 4. Staging: collect all files in memory (bounded courses are small) ──
        staged: dict[str, tuple[bytes, str]] = {}  # rel_path -> (data, media_type)

        # ── 5. Stage author assets ─────────────────────────────────────────────
        author_logical_paths: set[str] = set()
        for asset_ref in inp.author_assets:
            _assert_safe_bundle_path(asset_ref.logical_path, _RESERVED_NAMES)
            if asset_ref.logical_path in staged:
                raise AssemblyError(
                    f"Author asset collision: {asset_ref.logical_path!r} appears twice"
                )
            data = await self._store.get_bytes(asset_ref.artifact.uri)
            staged[asset_ref.logical_path] = (data, asset_ref.artifact.media_type)
            author_logical_paths.add(asset_ref.logical_path)

        # ── 6. Verify course JSON references are covered by author assets ──────
        for screen in course_dict.get("screens", []):
            if isinstance(screen, dict):
                image_path = screen.get("image_path")
                if image_path and image_path not in author_logical_paths:
                    raise AssemblyError(
                        f"Screen {screen.get('screen_id')!r} references asset "
                        f"{image_path!r} which is not in author_assets"
                    )

        # ── 7. Stage video, captions, and posters for each insertion ───────────
        screens = course_dict.get("screens", [])
        insertion_by_slot = {vi.slot_id: vi for vi in inp.video_insertions}

        updated_screens = []
        video_count = 0
        unresolved_count = 0

        for screen in screens:
            if not isinstance(screen, dict) or screen.get("type") != "video_slot":
                updated_screens.append(screen)
                continue

            slot_id = screen.get("slot_id", "")
            vi = insertion_by_slot.get(slot_id)

            if vi is None:
                # Not required to have an insertion — keep as-is but mark unresolved
                unresolved_count += 1
                updated_screens.append(screen)
                continue

            # Stage video
            video_name = f"assets/{_safe_bundle_name(slot_id, '.mp4')}"
            _assert_safe_bundle_path(video_name, _RESERVED_NAMES)
            video_data = await self._store.get_bytes(vi.video_uri)
            _validate_mp4_for_slide(video_data)
            staged[video_name] = (video_data, "video/mp4")

            # Stage captions (convert SRT→VTT if needed)
            captions_name: str | None = None
            if vi.captions_uri is not None:
                captions_name = f"assets/{_safe_bundle_name(slot_id, '.vtt')}"
                _assert_safe_bundle_path(captions_name, _RESERVED_NAMES)
                raw_captions = await self._store.get_bytes(vi.captions_uri)
                try:
                    vtt_bytes = ensure_vtt(raw_captions, vi.captions_media_type or "text/vtt")
                except CaptionConversionError as exc:
                    raise AssemblyError(
                        f"Caption conversion failed for slot {slot_id!r}: {exc}"
                    ) from exc
                staged[captions_name] = (vtt_bytes, "text/vtt")

            # Stage poster
            poster_name: str | None = None
            if vi.poster_uri is not None:
                poster_ext = ".png" if (vi.poster_media_type or "").endswith("png") else ".jpg"
                poster_name = f"assets/{_safe_bundle_name(slot_id + '-poster', poster_ext)}"
                _assert_safe_bundle_path(poster_name, _RESERVED_NAMES)
                poster_data = await self._store.get_bytes(vi.poster_uri)
                staged[poster_name] = (poster_data, vi.poster_media_type or "image/png")

            # Replace VideoSlotScreen with VideoPlayerScreen
            new_screen = {
                "type": "video_player",
                "screen_id": screen["screen_id"],
                "sequence": screen["sequence"],
                "rlo_source_refs": screen.get("rlo_source_refs", ["unknown"]),
                "title": vi.title or screen.get("title"),
                "video_src": video_name,
                "captions_path": captions_name,
                "poster_path": poster_name,
            }
            updated_screens.append(new_screen)
            video_count += 1

        # ── 8. Verify no unresolved required slots ─────────────────────────────
        final_course_dict = {**course_dict, "screens": updated_screens}
        final_report = validator.validate(final_course_dict, ())
        remaining_slots = final_report.discovered_slot_ids
        if remaining_slots:
            unresolved_count = len(remaining_slots)

        # Fail if any required slot was not resolved
        for req in inp.required_slots:
            if req.required and req.slot_id in remaining_slots:
                raise AssemblyError(
                    f"Required slot {req.slot_id!r} was not replaced — "
                    f"missing VideoInsertion or VideoSlotScreen not found"
                )

        # ── 9. Validate final CourseContent using pipeline bridge ──────────────
        from learning_pipeline.tools.elearning_bundle._pipeline_bridge import (
            CourseContent,
            render_course_html,
        )
        try:
            final_course = CourseContent.model_validate(final_course_dict)
        except Exception as exc:
            raise AssemblyError(f"Final CourseContent validation failed: {exc}") from exc

        # ── 10. Render final HTML ──────────────────────────────────────────────
        theme_id = final_course_dict.get("theme_id", "deloitte-green")
        try:
            html_str = render_course_html(final_course, theme_id=theme_id)
        except Exception as exc:
            raise AssemblyError(f"HTML rendering failed: {exc}") from exc

        html_bytes = html_str.encode("utf-8")
        output_html_name = inp.output_filename
        course_json_name = "course.course.json"
        manifest_name = "asset-manifest.json"

        # ── 11. Write final course JSON ────────────────────────────────────────
        final_course_bytes = json.dumps(
            final_course_dict, indent=2, ensure_ascii=False
        ).encode("utf-8")

        # ── 12. Generate asset manifest ────────────────────────────────────────
        asset_entries_for_manifest = [
            (path, data, mt) for path, (data, mt) in staged.items()
        ]
        manifest_bytes = _build_asset_manifest(
            output_html_name, course_json_name, asset_entries_for_manifest
        )

        # ── 13. Build deterministic ZIP ────────────────────────────────────────
        zip_files = [(output_html_name, html_bytes), (course_json_name, final_course_bytes)]
        for rel_path, (data, _) in staged.items():
            zip_files.append((rel_path, data))
        zip_bytes = _build_deterministic_zip(zip_files)

        # ── 14. Publish all output artifacts ──────────────────────────────────
        html_ref = await self._store.put_bytes(
            namespace=ns, name=output_html_name, data=html_bytes, media_type="text/html"
        )
        course_json_ref = await self._store.put_bytes(
            namespace=ns, name=course_json_name, data=final_course_bytes, media_type="application/json"
        )
        manifest_ref = await self._store.put_bytes(
            namespace=ns, name=manifest_name, data=manifest_bytes, media_type="application/json"
        )
        zip_ref = await self._store.put_bytes(
            namespace=ns,
            name=f"{inp.deliverable_id}.zip",
            data=zip_bytes,
            media_type="application/zip",
        )

        # ── 15. Validate and return output ─────────────────────────────────────
        try:
            output = ElearningBundleAssemblyOutput(
                entry_html=html_ref,
                course_json=course_json_ref,
                asset_manifest=manifest_ref,
                bundle_zip=zip_ref,
                screen_count=len(final_course.screens),
                video_count=video_count,
                unresolved_slot_count=unresolved_count,
            )
        except Exception as exc:
            raise InvalidToolOutputError(
                f"[{context.task_id}] ElearningBundleAssemblyOutput validation failed: {exc}"
            ) from exc

        return output.model_dump()
