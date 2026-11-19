from __future__ import annotations

import importlib
import io
import stat
import zipfile
from pathlib import Path
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient

from learning_commissioning.contracts import DeliverableDescriptor
from learning_pipeline.contracts import Modality


api_module = importlib.import_module("learning_commissioning.api.app")


def _write_course_zip(path: Path) -> None:
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            "index.html",
            '<video><track kind="captions" src="assets/captions.vtt"></video>',
        )
        archive.writestr("assets/captions.vtt", "WEBVTT\n\n00:00.000 --> 00:01.000\nHello\n")
        archive.writestr("assets/video.mp4", b"0123456789")


def _course_zip_bytes(tmp_path: Path) -> bytes:
    bundle = tmp_path / "course.zip"
    _write_course_zip(bundle)
    return bundle.read_bytes()


def _descriptor() -> DeliverableDescriptor:
    return DeliverableDescriptor(
        deliverable_id="bundle-1",
        filename="course.zip",
        media_type="application/zip",
        primary=True,
        download_url="/download",
    )


def test_preview_reads_html_and_captions_directly_from_bundle(tmp_path: Path) -> None:
    bundle = _course_zip_bytes(tmp_path)

    html, html_type = api_module._course_preview_asset(bundle, "index.html")
    captions, captions_type = api_module._course_preview_asset(
        bundle, "assets/captions.vtt"
    )

    assert html.startswith(b"<video>")
    assert html_type == "text/html"
    assert captions.startswith(b"WEBVTT")
    assert captions_type == "text/vtt"


@pytest.mark.parametrize("include_index", (False, True))
def test_preview_rejects_malformed_course_packages(
    tmp_path: Path,
    include_index: bool,
) -> None:
    if include_index:
        bundle = b"not a zip archive"
    else:
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("course.course.json", "{}")
        bundle = stream.getvalue()

    with pytest.raises(api_module.CoursePreviewError):
        api_module._course_preview_asset(bundle, "index.html")


@pytest.mark.parametrize("unsafe_name", ("../outside.txt", "/absolute.txt"))
def test_preview_rejects_unsafe_zip_paths(tmp_path: Path, unsafe_name: str) -> None:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("index.html", "course")
        archive.writestr(unsafe_name, "unsafe")

    with pytest.raises(api_module.CoursePreviewError, match="unsafe path"):
        api_module._course_preview_asset(stream.getvalue(), "index.html")
    assert not (tmp_path / "outside.txt").exists()


def test_preview_rejects_zip_links(tmp_path: Path) -> None:
    stream = io.BytesIO()
    link = zipfile.ZipInfo("assets/link")
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("index.html", "course")
        archive.writestr(link, "../../outside.txt")

    with pytest.raises(api_module.CoursePreviewError, match="unsafe path"):
        api_module._course_preview_asset(stream.getvalue(), "index.html")


def test_preview_rejects_unsafe_requested_path(tmp_path: Path) -> None:
    with pytest.raises(api_module.CoursePreviewError, match="unsafe"):
        api_module._course_preview_asset(_course_zip_bytes(tmp_path), "../secret.txt")


@pytest.mark.asyncio
async def test_course_preview_serves_html_captions_and_video_ranges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _course_zip_bytes(tmp_path)

    async def resolve(_job_id: str):
        return _descriptor(), bundle

    monkeypatch.setattr(api_module, "_resolve_course_bundle", resolve)
    async with AsyncClient(
        transport=ASGITransport(app=api_module.app),
        base_url="http://test",
    ) as client:
        redirect = await client.get(
            "/api/commissioning-jobs/job-1/preview",
            follow_redirects=False,
        )
        html = await client.get("/api/commissioning-jobs/job-1/preview/")
        captions = await client.get(
            "/api/commissioning-jobs/job-1/preview/assets/captions.vtt"
        )
        video = await client.get(
            "/api/commissioning-jobs/job-1/preview/assets/video.mp4",
            headers={"Range": "bytes=0-3"},
        )

    assert redirect.status_code in {302, 307}
    assert redirect.headers["location"].endswith("/preview/")
    assert html.status_code == 200
    assert html.headers["content-type"].startswith("text/html")
    assert html.headers["x-content-type-options"] == "nosniff"
    assert captions.status_code == 200
    assert captions.headers["content-type"].startswith("text/vtt")
    assert captions.text.startswith("WEBVTT")
    assert video.status_code == 206
    assert video.content == b"0123"


@pytest.mark.asyncio
async def test_course_bundle_resolution_rejects_other_modalities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def get_job(_job_id: str):
        return SimpleNamespace(selected_modality=Modality.PODCAST)

    monkeypatch.setattr(api_module, "_get_job_or_404", get_job)

    with pytest.raises(api_module.CoursePreviewError, match="only for e-learning"):
        await api_module._resolve_course_bundle("job-1")


@pytest.mark.asyncio
async def test_course_bundle_resolution_requires_a_primary_zip(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def get_job(_job_id: str):
        return SimpleNamespace(selected_modality=Modality.ELEARNING)

    async def completed(_job_id: str):
        return []

    monkeypatch.setattr(api_module, "_get_job_or_404", get_job)
    monkeypatch.setattr(api_module, "_completed_deliverables", completed)

    with pytest.raises(api_module.CoursePreviewError, match="does not contain"):
        await api_module._resolve_course_bundle("job-1")


@pytest.mark.asyncio
async def test_course_bundle_resolution_reads_logical_artifact_from_store(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bundle = _course_zip_bytes(tmp_path)

    async def get_job(_job_id: str):
        return SimpleNamespace(selected_modality=Modality.ELEARNING)

    async def completed(_job_id: str):
        return [(_descriptor(), "artifact://courses/job-1/course.zip")]

    class Store:
        async def get_bytes(self, uri: str) -> bytes:
            assert uri == "artifact://courses/job-1/course.zip"
            return bundle

    monkeypatch.setattr(api_module, "_get_job_or_404", get_job)
    monkeypatch.setattr(api_module, "_completed_deliverables", completed)
    monkeypatch.setattr(api_module, "_artifact_store", Store())

    descriptor, resolved = await api_module._resolve_course_bundle("job-1")

    assert descriptor.deliverable_id == "bundle-1"
    assert resolved == bundle
