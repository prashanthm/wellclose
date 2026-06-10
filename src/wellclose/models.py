"""Canonical data model (Brief §5.2). Facts are first-class with provenance; entities are
materialized views over approved facts; append-only — facts are superseded, never destroyed."""
from __future__ import annotations
import uuid
from datetime import datetime, timezone
from sqlalchemy import (JSON, Boolean, Computed, DateTime, Float, ForeignKey, Index, Integer,
                        String, Text)
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from pgvector.sqlalchemy import Vector

EMBED_DIM = 768  # open embedding model family (§16.2); change requires reindex


def _id() -> str:
    return uuid.uuid4().hex


def _now() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class Well(Base):
    __tablename__ = "well"
    well_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    api_number: Mapped[str | None] = mapped_column(String(14), index=True)   # US 12-digit normalized
    uwi: Mapped[str | None] = mapped_column(String(32), index=True)
    name: Mapped[str | None] = mapped_column(String(256))
    jurisdiction: Mapped[str] = mapped_column(String(16), default="TXRRC")    # BSEE|TXRRC|NSTA|NO
    operator_history: Mapped[list | None] = mapped_column(JSON)
    surface_lat: Mapped[float | None] = mapped_column(Float)
    surface_lon: Mapped[float | None] = mapped_column(Float)
    crs: Mapped[str | None] = mapped_column(String(64))
    spud_date: Mapped[str | None] = mapped_column(String(32))
    status: Mapped[str | None] = mapped_column(String(64))
    status_history: Mapped[list | None] = mapped_column(JSON)
    water_depth_ft: Mapped[float | None] = mapped_column(Float)
    ground_elevation_ft: Mapped[float | None] = mapped_column(Float)
    lease_block: Mapped[str | None] = mapped_column(String(128))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Wellbore(Base):
    __tablename__ = "wellbore"
    wellbore_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    parent_well_id: Mapped[str] = mapped_column(ForeignKey("well.well_id"), index=True)
    sidetrack_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    td_md_ft: Mapped[float | None] = mapped_column(Float)
    td_tvd_ft: Mapped[float | None] = mapped_column(Float)
    datum: Mapped[str | None] = mapped_column(String(16))  # KB|RT|MSL|datum_unknown (§5.4)
    trajectory_summary: Mapped[dict | None] = mapped_column(JSON)


class CasingString(Base):
    __tablename__ = "casing_string"
    casing_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    wellbore_id: Mapped[str] = mapped_column(ForeignKey("wellbore.wellbore_id"), index=True)
    size_od_in: Mapped[float | None] = mapped_column(Float)
    weight_ppf: Mapped[float | None] = mapped_column(Float)
    grade: Mapped[str | None] = mapped_column(String(32))
    top_md_ft: Mapped[float | None] = mapped_column(Float)
    shoe_md_ft: Mapped[float | None] = mapped_column(Float)
    cement_top_ft: Mapped[float | None] = mapped_column(Float)
    cement_top_basis: Mapped[str | None] = mapped_column(String(16))  # reported|CBL|calculated|unknown
    cement_volume: Mapped[str | None] = mapped_column(String(64))
    cement_class: Mapped[str | None] = mapped_column(String(32))
    pressure_tests: Mapped[list | None] = mapped_column(JSON)


class CompletionInterval(Base):
    __tablename__ = "completion_interval"
    interval_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    wellbore_id: Mapped[str] = mapped_column(ForeignKey("wellbore.wellbore_id"), index=True)
    top_md_ft: Mapped[float | None] = mapped_column(Float)
    base_md_ft: Mapped[float | None] = mapped_column(Float)
    formation: Mapped[str | None] = mapped_column(String(128))
    perforations: Mapped[list | None] = mapped_column(JSON)
    status: Mapped[str | None] = mapped_column(String(16))  # open|squeezed|isolated


class PluggingRecord(Base):
    __tablename__ = "plugging_record"
    plug_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    wellbore_id: Mapped[str] = mapped_column(ForeignKey("wellbore.wellbore_id"), index=True)
    plug_number: Mapped[int | None] = mapped_column(Integer)
    plug_type: Mapped[str | None] = mapped_column(String(32))  # cement|mechanical|cast_iron_bridge
    top_md_ft: Mapped[float | None] = mapped_column(Float)
    base_md_ft: Mapped[float | None] = mapped_column(Float)
    volume: Mapped[str | None] = mapped_column(String(64))
    verification_method: Mapped[str | None] = mapped_column(String(64))
    date: Mapped[str | None] = mapped_column(String(32))
    regulator_form_ref: Mapped[str | None] = mapped_column(String(64))


class WellboreEvent(Base):
    __tablename__ = "wellbore_event"
    event_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    wellbore_id: Mapped[str | None] = mapped_column(ForeignKey("wellbore.wellbore_id"), index=True)
    well_id: Mapped[str | None] = mapped_column(ForeignKey("well.well_id"), index=True)
    event_type: Mapped[str] = mapped_column(String(32))  # fish_lost|junk|casing_cut|stuck_pipe|sidetrack|squeeze|integrity_test|other
    date: Mapped[str | None] = mapped_column(String(32))
    depth_top_ft: Mapped[float | None] = mapped_column(Float)
    depth_base_ft: Mapped[float | None] = mapped_column(Float)
    narrative: Mapped[str | None] = mapped_column(Text)
    severity_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    source_fact_ids: Mapped[list | None] = mapped_column(JSON)


class Document(Base):
    __tablename__ = "document"
    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)  # sha256(raw_bytes) §4.5
    source: Mapped[str] = mapped_column(String(32))                          # bsee|txrrc|volve|upload
    source_url: Mapped[str | None] = mapped_column(Text)
    fetch_meta: Mapped[dict | None] = mapped_column(JSON)                    # ts, headers, checksum
    well_id: Mapped[str | None] = mapped_column(ForeignKey("well.well_id"), index=True)
    doc_type: Mapped[str | None] = mapped_column(String(48), index=True)     # §7C taxonomy
    doc_type_confidence: Mapped[float | None] = mapped_column(Float)
    page_count: Mapped[int | None] = mapped_column(Integer)
    ocr_quality_score: Mapped[float | None] = mapped_column(Float)
    raw_uri: Mapped[str | None] = mapped_column(Text)
    stage: Mapped[str] = mapped_column(String(16), default="acquired")       # acquired|rendered|classified|extracted|resolved|failed
    split_parent_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class DocumentPage(Base):
    __tablename__ = "document_page"
    page_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    document_id: Mapped[str] = mapped_column(ForeignKey("document.document_id"), index=True)
    page_number: Mapped[int] = mapped_column(Integer)
    image_uri: Mapped[str | None] = mapped_column(Text)
    ocr_text: Mapped[str | None] = mapped_column(Text)
    ocr_blocks_uri: Mapped[str | None] = mapped_column(Text)   # word-level boxes artifact
    ocr_quality: Mapped[float | None] = mapped_column(Float)
    low_quality: Mapped[bool] = mapped_column(Boolean, default=False)
    embedding: Mapped[list | None] = mapped_column(Vector(EMBED_DIM), nullable=True)
    search_tsv: Mapped[str | None] = mapped_column(
        TSVECTOR, Computed("to_tsvector('english', coalesce(ocr_text,''))", persisted=True))
    __table_args__ = (Index("ix_page_tsv", "search_tsv", postgresql_using="gin"),)


class ExtractedFact(Base):
    __tablename__ = "extracted_fact"
    fact_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    well_id: Mapped[str | None] = mapped_column(ForeignKey("well.well_id"), index=True)
    wellbore_id: Mapped[str | None] = mapped_column(String(32), index=True)
    entity_type: Mapped[str] = mapped_column(String(48))
    field_path: Mapped[str] = mapped_column(String(128), index=True)
    value: Mapped[str | None] = mapped_column(Text)
    unit: Mapped[str | None] = mapped_column(String(24))
    datum: Mapped[str | None] = mapped_column(String(16))
    document_id: Mapped[str] = mapped_column(ForeignKey("document.document_id"), index=True)
    page: Mapped[int] = mapped_column(Integer)                 # provenance REQUIRED (§8.3)
    bbox: Mapped[list | None] = mapped_column(JSON)
    snippet: Mapped[str] = mapped_column(Text)                 # provenance REQUIRED (§8.3)
    extraction_confidence: Mapped[float] = mapped_column(Float)
    verify_confidence: Mapped[float | None] = mapped_column(Float)  # pass-3 self-verify (§7D)
    derived_from_diagram: Mapped[bool] = mapped_column(Boolean, default=False)
    extractor_version: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(16), default="proposed", index=True)
    # proposed|approved|corrected|rejected|superseded
    corrected_value: Mapped[str | None] = mapped_column(Text)  # §9.4 training signal
    reviewer_id: Mapped[str | None] = mapped_column(String(64))
    review_timestamp: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    conflict_group_id: Mapped[str | None] = mapped_column(String(32), index=True)
    validation_flags: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class GapReport(Base):
    __tablename__ = "gap_report"
    gap_report_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    well_id: Mapped[str] = mapped_column(ForeignKey("well.well_id"), index=True)
    jurisdiction: Mapped[str] = mapped_column(String(16))
    coverage: Mapped[list] = mapped_column(JSON)               # per requirement: satisfied/by/conf
    gaps: Mapped[list] = mapped_column(JSON)                   # criticality-ranked, suggested sources
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Dossier(Base):
    __tablename__ = "dossier"
    dossier_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    well_id: Mapped[str] = mapped_column(ForeignKey("well.well_id"), index=True)
    version: Mapped[int] = mapped_column(Integer, default=1)
    gap_report_id: Mapped[str | None] = mapped_column(String(32))
    confidence_summary: Mapped[dict | None] = mapped_column(JSON)
    approved_facts_snapshot: Mapped[list] = mapped_column(JSON)  # immutable (§9.1 step 9)
    artifact_uris: Mapped[list] = mapped_column(JSON)
    signed_off_by: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class ToolCallLog(Base):
    __tablename__ = "tool_call_log"   # §8.7: every MCP call logged with agent identity + run id
    log_id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_id)
    agent: Mapped[str | None] = mapped_column(String(64))
    workflow_run_id: Mapped[str | None] = mapped_column(String(128), index=True)
    tool: Mapped[str] = mapped_column(String(64))
    args_summary: Mapped[dict | None] = mapped_column(JSON)
    well_id: Mapped[str | None] = mapped_column(String(32), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
