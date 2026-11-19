import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from src.source_ingestion import worker
from src.source_ingestion.extractors.epub import extract_epub
from src.source_ingestion.hierarchy import depth_first_nodes


def _epub_bytes() -> bytes:
    body = io.BytesIO()
    with zipfile.ZipFile(body, "w") as archive:
        archive.writestr(
            "mimetype",
            "application/epub+zip",
            compress_type=zipfile.ZIP_STORED,
        )
        archive.writestr(
            "META-INF/container.xml",
            """<?xml version="1.0"?>
            <container xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
              <rootfiles><rootfile full-path="EPUB/package.opf"/></rootfiles>
            </container>""",
        )
        archive.writestr(
            "EPUB/package.opf",
            """<?xml version="1.0"?>
            <package xmlns="http://www.idpf.org/2007/opf" version="3.0">
              <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
                <dc:title>Coffee Field Guide</dc:title>
                <dc:creator>Example Author</dc:creator>
              </metadata>
              <manifest>
                <item id="brew" href="brew.xhtml" media-type="application/xhtml+xml"/>
                <item id="beans" href="beans.xhtml" media-type="application/xhtml+xml"/>
              </manifest>
              <spine><itemref idref="beans"/><itemref idref="brew"/></spine>
            </package>""",
        )
        archive.writestr(
            "EPUB/beans.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><body>
            <h1>Select beans</h1><p>Choose beans suited to the intended flavor.</p>
            </body></html>""",
        )
        archive.writestr(
            "EPUB/brew.xhtml",
            """<html xmlns="http://www.w3.org/1999/xhtml"><body>
            <h1>Brew coffee</h1><ol><li>Insert the capsule.</li><li>Press brew.</li></ol>
            </body></html>""",
        )
    return body.getvalue()


def test_epub_adapter_preserves_spine_order_and_chapter_hierarchy(tmp_path: Path):
    path = tmp_path / "guide.epub"
    path.write_bytes(_epub_bytes())

    result = extract_epub(
        path,
        source_version_id="epub-version",
        extraction_run_id="epub-run",
    )

    ordered = depth_first_nodes(result.document)
    chapters = [node for node in ordered if node.kind == "chapter"]
    assert result.document.format == "epub"
    assert result.document.chapter_count == 2
    assert [node.text for node in chapters] == ["Select beans", "Brew coffee"]
    assert [node.locators[0].chapter for node in chapters] == [1, 2]
    assert all(node.ordinal_path[:1] == (0,) for node in ordered)
    assert [node.ordinal_path for node in result.document.nodes] == sorted(
        node.ordinal_path for node in result.document.nodes
    )
    assert "Insert the capsule." in [node.text for node in ordered]
    assert result.original["spine"][0]["href"] == "EPUB/beans.xhtml"


def test_epub_node_ids_are_stable_across_extraction_runs(tmp_path: Path):
    path = tmp_path / "guide.epub"
    path.write_bytes(_epub_bytes())

    first = extract_epub(
        path, source_version_id="same-version", extraction_run_id="run-1"
    )
    second = extract_epub(
        path, source_version_id="same-version", extraction_run_id="run-2"
    )

    assert [node.node_id for node in first.document.nodes] == [
        node.node_id for node in second.document.nodes
    ]


def test_epub_worker_persists_full_canonical_artifacts_and_segments():
    job = SimpleNamespace(
        job_id="epub-run",
        source_id="source-epub",
        source_version_id="version-epub",
        original_filename="guide.epub",
        minio_object_path="source-content/original/guide.epub",
    )
    storage = MagicMock()
    storage.get.return_value = _epub_bytes()

    with (
        patch.object(worker, "update_job_status") as update,
        patch.object(worker, "_index_segments") as index_segments,
    ):
        worker.process_job(job, storage)

    stored_keys = [call.args[0] for call in storage.put.call_args_list]
    assert any(key.endswith("document.json") for key in stored_keys)
    assert any(key.endswith("epub-original.json") for key in stored_keys)
    assert any(key.endswith("report.json") for key in stored_keys)
    assert any(key.endswith("segments.json") for key in stored_keys)
    segment_call = next(
        call for call in storage.put.call_args_list if call.args[0].endswith("segments.json")
    )
    assert json.loads(segment_call.args[1])
    assert stored_keys[-1].endswith("artifact-manifest.json")
    assert update.call_args.args[:2] == ("epub-run", "ready")
    assert update.call_args.kwargs["format_metadata"]["chapter_count"] == 2
    index_segments.assert_called_once()
