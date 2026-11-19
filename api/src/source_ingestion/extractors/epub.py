"""EPUB adapter producing spine-ordered canonical source nodes."""

from __future__ import annotations

import posixpath
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit
from xml.etree import ElementTree

from ..contracts import (
    DocumentNode,
    ExtractedDocument,
    ExtractionMethod,
    SourceFormat,
    SourceLocator,
)
from ..hierarchy import stable_node_id, validate_document
from ..rendering import RenderedArtifact


@dataclass(frozen=True)
class EpubExtraction:
    document: ExtractedDocument
    original: dict[str, Any]
    warnings: tuple[str, ...]
    artifacts: tuple[RenderedArtifact, ...] = ()


_BLOCK_KINDS = {
    "p": "paragraph",
    "pre": "preformatted",
    "blockquote": "blockquote",
    "li": "list_item",
    "dt": "term",
    "dd": "definition",
    "figcaption": "caption",
}


def _local_name(value: str) -> str:
    return value.rsplit("}", 1)[-1].lower()


def _normalized_text(element) -> str:
    return re.sub(r"\s+", " ", " ".join(element.itertext())).strip()


def _table_text(element) -> str:
    rows = []
    for row in element.iter():
        if _local_name(row.tag) != "tr":
            continue
        cells = [
            _normalized_text(cell)
            for cell in row
            if _local_name(cell.tag) in {"th", "td"} and _normalized_text(cell)
        ]
        if cells:
            rows.append(" | ".join(cells))
    return "\n".join(rows)


def _content_blocks(root) -> list[tuple[str, str]]:
    body = next((item for item in root.iter() if _local_name(item.tag) == "body"), root)
    blocks: list[tuple[str, str]] = []

    def walk(element) -> None:
        tag = _local_name(element.tag)
        if tag in {"script", "style", "svg"}:
            return
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            text = _normalized_text(element)
            if text:
                blocks.append(("heading", text))
            return
        if tag == "table":
            text = _table_text(element)
            if text:
                blocks.append(("table", text))
            return
        if tag in _BLOCK_KINDS:
            text = _normalized_text(element)
            if text:
                blocks.append((_BLOCK_KINDS[tag], text))
            return
        for child in element:
            walk(child)

    walk(body)
    return blocks


def _first_by_local_name(root, name: str):
    return next((item for item in root.iter() if _local_name(item.tag) == name), None)


def _opf_path(archive: zipfile.ZipFile) -> str:
    try:
        container = ElementTree.fromstring(archive.read("META-INF/container.xml"))
    except (KeyError, ElementTree.ParseError) as exc:
        raise ValueError("EPUB is missing a valid META-INF/container.xml") from exc
    rootfile = _first_by_local_name(container, "rootfile")
    path = rootfile.get("full-path") if rootfile is not None else None
    if not path:
        raise ValueError("EPUB container does not identify its package document")
    return path


def _archive_href(opf_path: str, href: str) -> str:
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc:
        raise ValueError(f"EPUB spine item uses an external href: {href}")
    return posixpath.normpath(
        posixpath.join(posixpath.dirname(opf_path), unquote(parsed.path))
    )


def extract_epub(
    path: Path,
    *,
    source_version_id: str,
    extraction_run_id: str,
) -> EpubExtraction:
    try:
        archive = zipfile.ZipFile(path)
    except zipfile.BadZipFile as exc:
        raise ValueError("invalid EPUB ZIP container") from exc

    with archive:
        opf_path = _opf_path(archive)
        try:
            package = ElementTree.fromstring(archive.read(opf_path))
        except (KeyError, ElementTree.ParseError) as exc:
            raise ValueError("EPUB package document is missing or invalid") from exc

        metadata = _first_by_local_name(package, "metadata")
        title_element = (
            _first_by_local_name(metadata, "title") if metadata is not None else None
        )
        creator_element = (
            _first_by_local_name(metadata, "creator") if metadata is not None else None
        )
        title = _normalized_text(title_element) if title_element is not None else path.stem
        creator = (
            _normalized_text(creator_element) if creator_element is not None else None
        )

        manifest = _first_by_local_name(package, "manifest")
        manifest_children = list(manifest) if manifest is not None else []
        manifest_items = {
            item.get("id"): item
            for item in manifest_children
            if _local_name(item.tag) == "item" and item.get("id") and item.get("href")
        }
        spine = _first_by_local_name(package, "spine")
        spine_children = list(spine) if spine is not None else []
        spine_items = [
            manifest_items[item.get("idref")]
            for item in spine_children
            if _local_name(item.tag) == "itemref"
            and item.get("linear", "yes") != "no"
            and item.get("idref") in manifest_items
        ]
        if not spine_items:
            raise ValueError("EPUB contains no readable linear spine items")

        root_id = stable_node_id(source_version_id, kind="document", ordinal_path=(0,))
        nodes: list[DocumentNode] = []
        chapter_nodes: list[DocumentNode] = []
        chapter_audit = []
        warnings: list[str] = []

        for chapter_index, item in enumerate(spine_items, start=1):
            href = _archive_href(opf_path, item.get("href"))
            try:
                chapter_root = ElementTree.fromstring(archive.read(href))
            except (KeyError, ElementTree.ParseError):
                warnings.append(f"unreadable_spine_item:{href}")
                continue
            blocks = _content_blocks(chapter_root)
            heading = next((text for kind, text in blocks if kind == "heading"), None)
            chapter_title = heading or f"Chapter {chapter_index}"
            chapter_ordinal = len(chapter_nodes)
            chapter_path = (0, chapter_ordinal)
            chapter_id = stable_node_id(
                source_version_id,
                kind="chapter",
                ordinal_path=chapter_path,
            )
            block_nodes = [
                DocumentNode(
                    node_id=stable_node_id(
                        source_version_id,
                        kind=kind,
                        ordinal_path=chapter_path + (block_ordinal,),
                    ),
                    parent_id=chapter_id,
                    ordinal=block_ordinal,
                    ordinal_path=chapter_path + (block_ordinal,),
                    kind=kind,
                    role="section_header" if kind == "heading" else kind,
                    text=text,
                    locators=[SourceLocator(chapter=chapter_index, href=href)],
                    method=ExtractionMethod.NATIVE,
                )
                for block_ordinal, (kind, text) in enumerate(blocks)
            ]
            chapter_nodes.append(
                DocumentNode(
                    node_id=chapter_id,
                    parent_id=root_id,
                    ordinal=chapter_ordinal,
                    ordinal_path=chapter_path,
                    kind="chapter",
                    role="chapter",
                    text=chapter_title,
                    locators=[SourceLocator(chapter=chapter_index, href=href)],
                    method=ExtractionMethod.NATIVE,
                    child_ids=[node.node_id for node in block_nodes],
                )
            )
            nodes.extend(block_nodes)
            chapter_audit.append(
                {"chapter": chapter_index, "href": href, "title": chapter_title}
            )

    if not chapter_nodes:
        raise ValueError("EPUB spine contained no parseable XHTML content")
    root = DocumentNode(
        node_id=root_id,
        ordinal=0,
        ordinal_path=(0,),
        kind="document",
        role="root",
        text=title,
        locators=[SourceLocator(chapter=1, href=chapter_audit[0]["href"])],
        method=ExtractionMethod.NATIVE,
        child_ids=[node.node_id for node in chapter_nodes],
    )
    document = validate_document(
        ExtractedDocument(
            source_version_id=source_version_id,
            extraction_run_id=extraction_run_id,
            format=SourceFormat.EPUB,
            chapter_count=len(spine_items),
            nodes=[
                root,
                *sorted([*chapter_nodes, *nodes], key=lambda node: node.ordinal_path),
            ],
        )
    )
    return EpubExtraction(
        document=document,
        original={
            "format": "epub",
            "package_path": opf_path,
            "title": title,
            "creator": creator,
            "spine": chapter_audit,
        },
        warnings=tuple(warnings),
    )
