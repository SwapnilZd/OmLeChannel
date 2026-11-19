"""Durable source/version/run persistence with atomic stage claims."""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import JSON, Boolean, Column, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, create_engine, func, select, update
from sqlalchemy.orm import Session, declarative_base, sessionmaker

Base = declarative_base()


class SourceDocumentRow(Base):
    __tablename__ = "source_documents"
    source_id = Column(String, primary_key=True)
    title = Column(Text, nullable=False)
    current_version_id = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class SourceVersionRow(Base):
    __tablename__ = "source_versions"
    source_version_id = Column(String, primary_key=True)
    source_id = Column(String, ForeignKey("source_documents.source_id", ondelete="CASCADE"), nullable=False, index=True)
    checksum = Column(String, nullable=False, unique=True, index=True)
    original_filename = Column(Text, nullable=False)
    content_type = Column(String, nullable=True)
    size_bytes = Column(Integer, nullable=False)
    uploader = Column(String, nullable=True)
    uploaded_at = Column(DateTime(timezone=True), nullable=False)
    original_object_key = Column(Text, nullable=False)


class SourceProcessingRunRow(Base):
    __tablename__ = "source_processing_runs"
    __table_args__ = (UniqueConstraint("source_version_id", "stage", "attempt"),)
    run_id = Column(String, primary_key=True)
    source_version_id = Column(String, ForeignKey("source_versions.source_version_id", ondelete="CASCADE"), nullable=False, index=True)
    stage = Column(String, nullable=False, default="extraction")
    attempt = Column(Integer, nullable=False, default=1)
    status = Column(String, nullable=False, default="queued", index=True)
    worker_id = Column(String, nullable=True)
    lease_expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    retryable = Column(Boolean, nullable=True)
    format_metadata = Column(JSON, nullable=True)
    artifact_manifest_object_key = Column(Text, nullable=True)


class SourceCollectionRow(Base):
    __tablename__ = "source_collections"
    collection_id = Column(String, primary_key=True)
    title = Column(Text, nullable=False)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class SourceCollectionMemberRow(Base):
    __tablename__ = "source_collection_members"
    __table_args__ = (
        UniqueConstraint("collection_id", "ordinal"),
        UniqueConstraint("collection_id", "source_version_id"),
    )
    collection_id = Column(String, ForeignKey("source_collections.collection_id", ondelete="CASCADE"), primary_key=True)
    source_version_id = Column(String, ForeignKey("source_versions.source_version_id", ondelete="CASCADE"), primary_key=True)
    ordinal = Column(Integer, nullable=False)
    authority_note = Column(Text, nullable=True)


class SourceMapArtifactRow(Base):
    __tablename__ = "source_map_artifacts"
    __table_args__ = (
        UniqueConstraint("scope_kind", "scope_id", "hierarchy_key", "map_revision"),
    )
    map_id = Column(String, primary_key=True)
    scope_kind = Column(String, nullable=False)
    scope_id = Column(String, nullable=False)
    hierarchy_key = Column(Text, nullable=False)
    map_revision = Column(String, nullable=False)
    model_alias = Column(String, nullable=False)
    prompt_template = Column(Text, nullable=False)
    input_node_ids = Column(JSON, nullable=False)
    token_usage = Column(JSON, nullable=False)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


@dataclass(frozen=True)
class SourceJobRecord:
    job_id: str
    source_id: str
    source_version_id: str
    status: str
    original_filename: str
    content_type: str | None
    size_bytes: int
    checksum: str
    uploader: str | None
    uploaded_at: datetime
    minio_object_path: str
    error_message: str | None
    format_metadata: dict | None
    attempt: int
    worker_id: str | None
    retryable: bool | None


@dataclass(frozen=True)
class SourceCollectionMemberRecord:
    source_version_id: str
    ordinal: int
    authority_note: str | None


@dataclass(frozen=True)
class SourceCollectionRecord:
    collection_id: str
    title: str
    created_by: str | None
    created_at: datetime
    members: tuple[SourceCollectionMemberRecord, ...]


@dataclass(frozen=True)
class SourceMapArtifactRecord:
    map_id: str
    scope_kind: str
    scope_id: str
    hierarchy_key: str
    map_revision: str
    model_alias: str
    prompt_template: str
    input_node_ids: tuple[str, ...]
    token_usage: dict
    payload: dict
    created_at: datetime


class InvalidStateTransition(ValueError):
    pass


_engine = None
_session_factory = None


def _database_url() -> str:
    database_url = os.environ.get("SOURCE_INGESTION_DATABASE_URL", "").strip()
    if not database_url:
        raise RuntimeError("SOURCE_INGESTION_DATABASE_URL is required")
    if not database_url.startswith("postgresql+psycopg://"):
        raise RuntimeError("SOURCE_INGESTION_DATABASE_URL must use postgresql+psycopg")
    return database_url


def _get_engine():
    return create_engine(_database_url(), pool_pre_ping=True)


def _init() -> None:
    global _engine, _session_factory
    if _engine is None:
        _engine = _get_engine()
        from .migrate import run_migrations

        run_migrations(_engine)
        _session_factory = sessionmaker(bind=_engine, expire_on_commit=False)


def reset_repository_for_tests() -> None:
    global _engine, _session_factory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _session_factory = None


def get_session() -> Session:
    _init()
    return _session_factory()


def init_db() -> None:
    _init()


def _record(session: Session, run: SourceProcessingRunRow) -> SourceJobRecord:
    version = session.get(SourceVersionRow, run.source_version_id)
    uploaded_at = version.uploaded_at
    if uploaded_at.tzinfo is None:
        uploaded_at = uploaded_at.replace(tzinfo=timezone.utc)
    return SourceJobRecord(
        job_id=run.run_id, source_id=version.source_id,
        source_version_id=version.source_version_id, status=run.status,
        original_filename=version.original_filename, content_type=version.content_type,
        size_bytes=version.size_bytes, checksum=version.checksum, uploader=version.uploader,
        uploaded_at=uploaded_at, minio_object_path=version.original_object_key,
        error_message=run.error_message, format_metadata=run.format_metadata,
        attempt=run.attempt, worker_id=run.worker_id, retryable=run.retryable,
    )


def create_job(job_id: str, source_id: str, original_filename: str, content_type: str | None, size_bytes: int, checksum: str, minio_object_path: str, uploader: str | None = None) -> SourceJobRecord:
    now = datetime.now(timezone.utc)
    version_id = str(uuid.uuid4())
    with get_session() as session, session.begin():
        document = session.get(SourceDocumentRow, source_id)
        if document is None:
            document = SourceDocumentRow(source_id=source_id, title=original_filename, current_version_id=version_id, created_at=now)
            session.add(document)
            session.flush()
        else:
            document.current_version_id = version_id
        version = SourceVersionRow(source_version_id=version_id, source_id=source_id, checksum=checksum, original_filename=original_filename, content_type=content_type, size_bytes=size_bytes, uploader=uploader, uploaded_at=now, original_object_key=minio_object_path)
        run = SourceProcessingRunRow(run_id=job_id, source_version_id=version_id, stage="extraction", attempt=1, status="queued", created_at=now)
        session.add(version)
        session.flush()
        session.add(run)
        session.flush()
        return _record(session, run)


def get_job(job_id: str) -> SourceJobRecord | None:
    with get_session() as session:
        run = session.get(SourceProcessingRunRow, job_id)
        return _record(session, run) if run else None


def get_latest_job_for_source_version(source_version_id: str) -> SourceJobRecord | None:
    with get_session() as session:
        run = session.scalar(
            select(SourceProcessingRunRow)
            .where(SourceProcessingRunRow.source_version_id == source_version_id)
            .order_by(SourceProcessingRunRow.attempt.desc())
            .limit(1)
        )
        return _record(session, run) if run else None


def list_jobs() -> list[SourceJobRecord]:
    with get_session() as session:
        runs = session.scalars(select(SourceProcessingRunRow).order_by(SourceProcessingRunRow.created_at.desc())).all()
        return [_record(session, run) for run in runs]


def get_artifact_manifest_object_key(job_id: str) -> str | None:
    with get_session() as session:
        run = session.get(SourceProcessingRunRow, job_id)
        return run.artifact_manifest_object_key if run else None


def claim_next_queued_job(worker_id: str = "source-worker", lease_seconds: int = 300) -> SourceJobRecord | None:
    now = datetime.now(timezone.utc)
    with get_session() as session, session.begin():
        run = session.scalars(select(SourceProcessingRunRow).where(SourceProcessingRunRow.status == "queued").order_by(SourceProcessingRunRow.created_at.asc()).with_for_update(skip_locked=True).limit(1)).first()
        if run is None:
            return None
        run.status = "processing"
        run.worker_id = worker_id
        run.started_at = now
        run.lease_expires_at = now + timedelta(seconds=lease_seconds)
        session.flush()
        return _record(session, run)


def update_job_status(job_id: str, status: str, error_message: str | None = None, format_metadata: dict | None = None, *, expected_status: str | None = None, artifact_manifest_object_key: str | None = None, retryable: bool | None = None) -> SourceJobRecord | None:
    with get_session() as session, session.begin():
        run = session.get(SourceProcessingRunRow, job_id)
        if run is None:
            return None
        if expected_status is not None and run.status != expected_status:
            raise InvalidStateTransition(f"run {job_id!r} is {run.status!r}, expected {expected_status!r}")
        run.status = status
        run.error_message = error_message
        run.retryable = retryable
        if format_metadata is not None:
            run.format_metadata = format_metadata
        if artifact_manifest_object_key is not None:
            run.artifact_manifest_object_key = artifact_manifest_object_key
        if status in {"ready", "failed"}:
            run.completed_at = datetime.now(timezone.utc)
            run.lease_expires_at = None
        session.flush()
        return _record(session, run)


def retry_job(job_id: str) -> SourceJobRecord:
    now = datetime.now(timezone.utc)
    with get_session() as session, session.begin():
        previous = session.get(SourceProcessingRunRow, job_id)
        if previous is None or previous.status != "failed":
            raise InvalidStateTransition("only failed runs can be retried")
        if previous.retryable is False:
            raise InvalidStateTransition("run failed with a non-retryable error")
        if previous.attempt >= 3:
            raise InvalidStateTransition("maximum extraction attempts reached")
        run = SourceProcessingRunRow(run_id=str(uuid.uuid4()), source_version_id=previous.source_version_id, stage=previous.stage, attempt=previous.attempt + 1, status="queued", created_at=now)
        session.add(run)
        session.flush()
        return _record(session, run)


def recover_stale_jobs(now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    with get_session() as session, session.begin():
        result = session.execute(update(SourceProcessingRunRow).where(SourceProcessingRunRow.status == "processing", SourceProcessingRunRow.lease_expires_at < now).values(status="queued", worker_id=None, lease_expires_at=None))
        return result.rowcount


def find_by_checksum(checksum: str) -> SourceJobRecord | None:
    with get_session() as session:
        version = session.scalar(select(SourceVersionRow).where(SourceVersionRow.checksum == checksum))
        if version is None:
            return None
        run = session.scalar(select(SourceProcessingRunRow).where(SourceProcessingRunRow.source_version_id == version.source_version_id).order_by(SourceProcessingRunRow.attempt.desc()))
        return _record(session, run)


def delete_job(job_id: str) -> bool:
    with get_session() as session, session.begin():
        run = session.get(SourceProcessingRunRow, job_id)
        if run is None:
            return False
        version = session.get(SourceVersionRow, run.source_version_id)
        document = session.get(SourceDocumentRow, version.source_id)
        session.delete(document)
        return True


def delete_all_jobs() -> None:
    with get_session() as session, session.begin():
        for document in session.scalars(select(SourceDocumentRow)).all():
            session.delete(document)


def create_source_collection(
    collection_id: str,
    title: str,
    members: list[tuple[str, str | None]],
    created_by: str | None = None,
) -> SourceCollectionRecord:
    if not collection_id or not title.strip():
        raise ValueError("collection ID and title are required")
    source_version_ids = [source_version_id for source_version_id, _ in members]
    if not source_version_ids:
        raise ValueError("collection requires at least one source version")
    if len(source_version_ids) != len(set(source_version_ids)):
        raise ValueError("duplicate source version in collection")
    now = datetime.now(timezone.utc)
    with get_session() as session, session.begin():
        missing = [
            source_version_id
            for source_version_id in source_version_ids
            if session.get(SourceVersionRow, source_version_id) is None
        ]
        if missing:
            raise ValueError(f"unknown source version: {missing[0]}")
        session.add(
            SourceCollectionRow(
                collection_id=collection_id,
                title=title.strip(),
                created_by=created_by,
                created_at=now,
            )
        )
        session.flush()
        for ordinal, (source_version_id, authority_note) in enumerate(members):
            session.add(
                SourceCollectionMemberRow(
                    collection_id=collection_id,
                    source_version_id=source_version_id,
                    ordinal=ordinal,
                    authority_note=authority_note,
                )
            )
        session.flush()
    result = get_source_collection(collection_id)
    if result is None:
        raise RuntimeError("created collection could not be loaded")
    return result


def get_source_collection(collection_id: str) -> SourceCollectionRecord | None:
    with get_session() as session:
        collection = session.get(SourceCollectionRow, collection_id)
        if collection is None:
            return None
        created_at = collection.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        members = session.scalars(
            select(SourceCollectionMemberRow)
            .where(SourceCollectionMemberRow.collection_id == collection_id)
            .order_by(SourceCollectionMemberRow.ordinal)
        ).all()
        return SourceCollectionRecord(
            collection_id=collection.collection_id,
            title=collection.title,
            created_by=collection.created_by,
            created_at=created_at,
            members=tuple(
                SourceCollectionMemberRecord(
                    source_version_id=member.source_version_id,
                    ordinal=member.ordinal,
                    authority_note=member.authority_note,
                )
                for member in members
            ),
        )


def _map_artifact_record(row: SourceMapArtifactRow) -> SourceMapArtifactRecord:
    created_at = row.created_at
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)
    return SourceMapArtifactRecord(
        map_id=row.map_id,
        scope_kind=row.scope_kind,
        scope_id=row.scope_id,
        hierarchy_key=row.hierarchy_key,
        map_revision=row.map_revision,
        model_alias=row.model_alias,
        prompt_template=row.prompt_template,
        input_node_ids=tuple(row.input_node_ids),
        token_usage=dict(row.token_usage),
        payload=dict(row.payload),
        created_at=created_at,
    )


def get_source_map_artifact(
    scope_kind: str,
    scope_id: str,
    hierarchy_key: str,
    map_revision: str,
) -> SourceMapArtifactRecord | None:
    with get_session() as session:
        row = session.scalar(
            select(SourceMapArtifactRow).where(
                SourceMapArtifactRow.scope_kind == scope_kind,
                SourceMapArtifactRow.scope_id == scope_id,
                SourceMapArtifactRow.hierarchy_key == hierarchy_key,
                SourceMapArtifactRow.map_revision == map_revision,
            )
        )
        return _map_artifact_record(row) if row else None


def count_source_map_artifacts(scope_kind: str, scope_id: str) -> int:
    with get_session() as session:
        return int(
            session.scalar(
                select(func.count(SourceMapArtifactRow.map_id)).where(
                    SourceMapArtifactRow.scope_kind == scope_kind,
                    SourceMapArtifactRow.scope_id == scope_id,
                )
            )
            or 0
        )


def save_source_map_artifact(
    *,
    map_id: str,
    scope_kind: str,
    scope_id: str,
    hierarchy_key: str,
    map_revision: str,
    model_alias: str,
    prompt_template: str,
    input_node_ids: list[str],
    token_usage: dict,
    payload: dict,
) -> SourceMapArtifactRecord:
    with get_session() as session, session.begin():
        existing = session.scalar(
            select(SourceMapArtifactRow).where(
                SourceMapArtifactRow.scope_kind == scope_kind,
                SourceMapArtifactRow.scope_id == scope_id,
                SourceMapArtifactRow.hierarchy_key == hierarchy_key,
                SourceMapArtifactRow.map_revision == map_revision,
            )
        )
        if existing is not None:
            return _map_artifact_record(existing)
        row = SourceMapArtifactRow(
            map_id=map_id,
            scope_kind=scope_kind,
            scope_id=scope_id,
            hierarchy_key=hierarchy_key,
            map_revision=map_revision,
            model_alias=model_alias,
            prompt_template=prompt_template,
            input_node_ids=input_node_ids,
            token_usage=token_usage,
            payload=payload,
            created_at=datetime.now(timezone.utc),
        )
        session.add(row)
        session.flush()
        return _map_artifact_record(row)
