"""Postgres persistence for learning briefs and objective workspaces."""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text, select
from sqlalchemy.orm import declarative_base

from src.source_ingestion.repository import get_session

from .contracts import LearningBrief, ObjectiveDecision, ObjectiveWorkspace


Base = declarative_base()


class LearningBriefRow(Base):
    __tablename__ = "source_learning_briefs"
    brief_id = Column(String, primary_key=True)
    collection_id = Column(String, nullable=False)
    source_map_revision = Column(String, nullable=False)
    brief_revision = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class ObjectiveWorkspaceRow(Base):
    __tablename__ = "source_objective_workspaces"
    workspace_id = Column(String, primary_key=True)
    collection_id = Column(String, nullable=False)
    created_by = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)


class ObjectiveWorkspaceRevisionRow(Base):
    __tablename__ = "source_objective_workspace_revisions"
    workspace_id = Column(
        String,
        ForeignKey("source_objective_workspaces.workspace_id", ondelete="CASCADE"),
        primary_key=True,
    )
    revision = Column(Integer, primary_key=True)
    brief_id = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)
    model_metadata = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), nullable=False)


class ObjectiveDecisionRow(Base):
    __tablename__ = "source_objective_decisions"
    workspace_id = Column(
        String,
        ForeignKey("source_objective_workspaces.workspace_id", ondelete="CASCADE"),
        primary_key=True,
    )
    revision = Column(Integer, primary_key=True)
    candidate_id = Column(String, primary_key=True)
    status = Column(String, nullable=False)
    note = Column(Text, nullable=True)
    decided_by = Column(String, nullable=False)
    decided_at = Column(DateTime(timezone=True), nullable=False)


def save_learning_brief(brief: LearningBrief) -> LearningBrief:
    with get_session() as session, session.begin():
        existing = session.scalar(
            select(LearningBriefRow).where(
                LearningBriefRow.collection_id == brief.collection_id,
                LearningBriefRow.brief_revision == brief.brief_revision,
            )
        )
        if existing:
            return LearningBrief.model_validate(existing.payload)
        session.add(
            LearningBriefRow(
                brief_id=brief.brief_id,
                collection_id=brief.collection_id,
                source_map_revision=brief.source_map_revision,
                brief_revision=brief.brief_revision,
                payload=brief.model_dump(mode="json"),
                created_at=datetime.now(timezone.utc),
            )
        )
    return brief


def create_objective_workspace(
    workspace_id: str,
    collection_id: str,
    *,
    created_by: str | None = None,
) -> None:
    with get_session() as session, session.begin():
        existing = session.get(ObjectiveWorkspaceRow, workspace_id)
        if existing:
            if existing.collection_id != collection_id:
                raise ValueError("workspace belongs to another collection")
            return
        session.add(
            ObjectiveWorkspaceRow(
                workspace_id=workspace_id,
                collection_id=collection_id,
                created_by=created_by,
                created_at=datetime.now(timezone.utc),
            )
        )


def save_workspace_revision(
    workspace: ObjectiveWorkspace,
    *,
    model_metadata: dict,
) -> ObjectiveWorkspace:
    with get_session() as session, session.begin():
        parent = session.get(ObjectiveWorkspaceRow, workspace.workspace_id)
        if parent is None:
            raise ValueError("objective workspace does not exist")
        if parent.collection_id != workspace.collection_id:
            raise ValueError("workspace collection mismatch")
        existing = session.get(
            ObjectiveWorkspaceRevisionRow,
            (workspace.workspace_id, workspace.revision),
        )
        if existing:
            return ObjectiveWorkspace.model_validate(existing.payload)
        session.add(
            ObjectiveWorkspaceRevisionRow(
                workspace_id=workspace.workspace_id,
                revision=workspace.revision,
                brief_id=workspace.learning_brief.brief_id,
                payload=workspace.model_dump(mode="json"),
                model_metadata=model_metadata,
                created_at=datetime.now(timezone.utc),
            )
        )
    return workspace


def record_objective_decision(
    workspace_id: str,
    revision: int,
    decision: ObjectiveDecision,
) -> ObjectiveDecision:
    with get_session() as session, session.begin():
        workspace = session.get(ObjectiveWorkspaceRevisionRow, (workspace_id, revision))
        if workspace is None:
            raise ValueError("objective workspace revision does not exist")
        row = session.get(
            ObjectiveDecisionRow,
            (workspace_id, revision, decision.candidate_id),
        )
        if row is None:
            row = ObjectiveDecisionRow(
                workspace_id=workspace_id,
                revision=revision,
                candidate_id=decision.candidate_id,
                decided_at=datetime.now(timezone.utc),
            )
            session.add(row)
        row.status = str(decision.status)
        row.note = decision.note
        row.decided_by = decision.decided_by
    return decision


def get_objective_workspace(
    workspace_id: str,
    revision: int | None = None,
) -> ObjectiveWorkspace | None:
    with get_session() as session:
        if revision is None:
            row = session.scalar(
                select(ObjectiveWorkspaceRevisionRow)
                .where(ObjectiveWorkspaceRevisionRow.workspace_id == workspace_id)
                .order_by(ObjectiveWorkspaceRevisionRow.revision.desc())
                .limit(1)
            )
        else:
            row = session.get(ObjectiveWorkspaceRevisionRow, (workspace_id, revision))
        if row is None:
            return None
        workspace = ObjectiveWorkspace.model_validate(row.payload)
        decisions = session.scalars(
            select(ObjectiveDecisionRow).where(
                ObjectiveDecisionRow.workspace_id == workspace_id,
                ObjectiveDecisionRow.revision == workspace.revision,
            )
        ).all()
        return workspace.model_copy(
            update={
                "decisions": [
                    ObjectiveDecision(
                        candidate_id=decision.candidate_id,
                        status=decision.status,
                        note=decision.note,
                        decided_by=decision.decided_by,
                    )
                    for decision in decisions
                ]
            }
        )


def get_workspace_model_metadata(workspace_id: str, revision: int) -> dict:
    with get_session() as session:
        row = session.get(ObjectiveWorkspaceRevisionRow, (workspace_id, revision))
        return dict(row.model_metadata) if row else {}
