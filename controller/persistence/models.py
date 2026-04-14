import uuid
from datetime import datetime

import sqlalchemy as sa
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.orm import Mapped, mapped_column, relationship

from shared.enums import (
    AssetType,
    EpisodeStatus,
    EpisodeType,
    GenerationKind,
    SeedMatchMethod,
    TraceType,
)

from .db import Base


class BenchmarkAsset(Base):
    __tablename__ = "benchmark_assets"

    benchmark_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, index=True
    )
    mjcf_url: Mapped[str] = mapped_column(String)
    build123d_url: Mapped[str] = mapped_column(String)
    preview_bundle_url: Mapped[str] = mapped_column(String)
    random_variants: Mapped[dict | None] = mapped_column(JSON)
    difficulty_score: Mapped[float | None] = mapped_column(sa.Float)
    benchmark_metadata: Mapped[dict | None] = mapped_column("metadata", JSON)


class DatasetRowArchive(Base):
    __tablename__ = "dataset_row_archives"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    episode_id: Mapped[uuid.UUID] = mapped_column(sa.UUID, ForeignKey("episodes.id"))
    user_session_id: Mapped[uuid.UUID | None] = mapped_column(sa.UUID, index=True)
    worker_session_id: Mapped[str | None] = mapped_column(String)
    benchmark_id: Mapped[uuid.UUID] = mapped_column(sa.UUID, index=True)
    episode_type: Mapped[EpisodeType] = mapped_column(
        SQLEnum(
            EpisodeType,
            name="episodetype",
            values_callable=lambda x: [e.value for e in x],
        )
    )

    seed_id: Mapped[str | None] = mapped_column(String)
    seed_dataset: Mapped[str | None] = mapped_column(String)
    seed_match_method: Mapped[SeedMatchMethod | None] = mapped_column(
        SQLEnum(
            SeedMatchMethod,
            name="seedmatchmethod",
            values_callable=lambda x: [e.value for e in x],
        )
    )
    generation_kind: Mapped[GenerationKind | None] = mapped_column(
        SQLEnum(
            GenerationKind,
            name="generationkind",
            values_callable=lambda x: [e.value for e in x],
        )
    )
    parent_seed_id: Mapped[str | None] = mapped_column(String)
    is_integration_test: Mapped[bool | None] = mapped_column(sa.Boolean)
    integration_test_id: Mapped[str | None] = mapped_column(String)

    simulation_run_id: Mapped[str | None] = mapped_column(String)
    cots_query_id: Mapped[str | None] = mapped_column(String)
    review_id: Mapped[str | None] = mapped_column(String)
    revision_hash: Mapped[str] = mapped_column(String)
    artifact_hash: Mapped[str] = mapped_column(String)

    archive_bucket: Mapped[str] = mapped_column(String)
    archive_key: Mapped[str] = mapped_column(String)
    archive_sha256: Mapped[str] = mapped_column(String)
    archive_size_bytes: Mapped[int] = mapped_column(Integer)
    manifest_bucket: Mapped[str] = mapped_column(String)
    manifest_key: Mapped[str] = mapped_column(String)
    manifest_sha256: Mapped[str] = mapped_column(String)
    manifest_size_bytes: Mapped[int] = mapped_column(Integer)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class GenerationSession(Base):
    __tablename__ = "generation_sessions"

    session_id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True, default=uuid.uuid4, index=True
    )
    prompt: Mapped[str] = mapped_column(String)
    status: Mapped[str | None] = mapped_column(
        sa.Enum(
            "planning",
            "planned",
            "executing",
            "validating",
            "accepted",
            "rejected",
            "failed",
            name="sessionstatus",
        )
    )
    validation_logs: Mapped[dict | None] = mapped_column(JSON)


class Episode(Base):
    __tablename__ = "episodes"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_session_id: Mapped[uuid.UUID | None] = mapped_column(
        sa.UUID, index=True
    )  # UI conversation scope
    task: Mapped[str] = mapped_column(String)
    status: Mapped[EpisodeStatus] = mapped_column(
        SQLEnum(EpisodeStatus, values_callable=lambda x: [e.value for e in x]),
        default=EpisodeStatus.RUNNING,
    )
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    # Reproducibility metadata
    skill_git_hash: Mapped[str | None] = mapped_column(String)
    template_versions: Mapped[dict | None] = mapped_column(JSON)
    metadata_vars: Mapped[dict | None] = mapped_column(JSON)
    seed_id: Mapped[str | None] = mapped_column(String, index=True)
    seed_dataset: Mapped[str | None] = mapped_column(String)
    seed_match_method: Mapped[SeedMatchMethod | None] = mapped_column(
        SQLEnum(SeedMatchMethod, values_callable=lambda x: [e.value for e in x])
    )
    generation_kind: Mapped[GenerationKind | None] = mapped_column(
        SQLEnum(GenerationKind, values_callable=lambda x: [e.value for e in x])
    )
    parent_seed_id: Mapped[str | None] = mapped_column(String)

    # Agent state
    todo_list: Mapped[dict | None] = mapped_column(JSON)
    journal: Mapped[str | None] = mapped_column(String)
    plan: Mapped[str | None] = mapped_column(String)

    traces: Mapped[list["Trace"]] = relationship(
        back_populates="episode", cascade="all, delete-orphan"
    )
    assets: Mapped[list["Asset"]] = relationship(
        back_populates="episode", cascade="all, delete-orphan"
    )

    @property
    def validation_logs(self) -> list[str] | None:
        if self.metadata_vars:
            return self.metadata_vars.get("validation_logs")
        return None


def _sync_episode_lineage_fields(target: Episode) -> None:
    from shared.models.schemas import EpisodeMetadata

    metadata = EpisodeMetadata.model_validate(target.metadata_vars or {})
    target.seed_id = metadata.seed_id
    target.seed_dataset = metadata.seed_dataset
    target.seed_match_method = metadata.seed_match_method
    target.generation_kind = metadata.generation_kind
    target.parent_seed_id = metadata.parent_seed_id


@sa.event.listens_for(Episode, "before_insert")
def _episode_before_insert(_, __, target: Episode) -> None:
    _sync_episode_lineage_fields(target)


@sa.event.listens_for(Episode, "before_update")
def _episode_before_update(_, __, target: Episode) -> None:
    _sync_episode_lineage_fields(target)


class Trace(Base):
    __tablename__ = "traces"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    episode_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("episodes.id"))
    user_session_id: Mapped[uuid.UUID | None] = mapped_column(sa.UUID, index=True)
    langfuse_trace_id: Mapped[str | None] = mapped_column(String)

    # Specific IDs for child artifacts
    simulation_run_id: Mapped[str | None] = mapped_column(String)
    cots_query_id: Mapped[str | None] = mapped_column(String)
    review_id: Mapped[str | None] = mapped_column(String)

    trace_type: Mapped[TraceType] = mapped_column(
        SQLEnum(TraceType, values_callable=lambda x: [e.value for e in x])
    )
    name: Mapped[str | None] = mapped_column(String)  # Tool name or stage
    content: Mapped[str | None] = mapped_column(
        String
    )  # Tool input/output or LLM content
    metadata_vars: Mapped[dict | None] = mapped_column(
        "metadata", JSON
    )  # Additional data
    feedback_score: Mapped[int | None] = mapped_column(Integer)  # 1 for up, 0 for down
    feedback_comment: Mapped[str | None] = mapped_column(String)

    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    episode: Mapped["Episode"] = relationship(back_populates="traces")


class Asset(Base):
    __tablename__ = "assets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    episode_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("episodes.id"))
    user_session_id: Mapped[uuid.UUID | None] = mapped_column(sa.UUID, index=True)
    asset_type: Mapped[AssetType] = mapped_column(
        SQLEnum(AssetType, values_callable=lambda x: [e.value for e in x])
    )
    s3_path: Mapped[str] = mapped_column(String)
    content: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    episode: Mapped["Episode"] = relationship(back_populates="assets")
