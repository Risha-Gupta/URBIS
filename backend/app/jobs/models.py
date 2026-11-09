import enum, uuid
from datetime import datetime, timezone
from sqlalchemy import String, Integer, Float, Text, ForeignKey, JSON, DateTime, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .db import Base

def now(): return datetime.now(timezone.utc)
def new_id(): return uuid.uuid4().hex[:12]

class JobStatus(str, enum.Enum):
    queued = "queued"
    preprocessing = "preprocessing"
    corner_detection = "corner_detection"
    edge_prediction = "edge_prediction"
    mesh_generation = "mesh_generation"
    uncertainty_analysis = "uncertainty_analysis"
    correction = "correction"
    completed = "completed"
    failed = "failed"

STAGES = [JobStatus.preprocessing, JobStatus.corner_detection, JobStatus.edge_prediction,
          JobStatus.mesh_generation, JobStatus.uncertainty_analysis, JobStatus.correction]
ACTIVE = {s.value for s in STAGES} | {"queued"}

class Job(Base):
    __tablename__ = "recon_jobs"
    id: Mapped[str] = mapped_column(String(12), primary_key=True, default=new_id)
    building_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    input_path: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(32), default="queued", index=True)
    review_status: Mapped[str] = mapped_column(String(20), default="none")  # none|pending|approved|rejected
    progress: Mapped[int] = mapped_column(Integer, default=0)
    final_version_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now, onupdate=now)
    versions = relationship("ModelResultVersion", back_populates="job", order_by="ModelResultVersion.version_no")

class ModelResultVersion(Base):
    __tablename__ = "model_result_versions"
    __table_args__ = (UniqueConstraint("job_id", "version_no"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("recon_jobs.id"), index=True)
    version_no: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16), default="running")  # running|succeeded|failed
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    stage_reached: Mapped[str | None] = mapped_column(String(32), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    action: Mapped[str | None] = mapped_column(String(20), nullable=True)   # ACCEPT|ACCEPT_FLAG|ESCALATE
    n_corners: Mapped[int | None] = mapped_column(Integer, nullable=True)
    n_edges: Mapped[int | None] = mapped_column(Integer, nullable=True)
    mesh_path: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    decision: Mapped[str | None] = mapped_column(String(16), nullable=True)  # approved|rejected
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    job = relationship("Job", back_populates="versions")

class JobEvent(Base):
    __tablename__ = "job_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("recon_jobs.id"), index=True)
    version_no: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32))
    progress: Mapped[int] = mapped_column(Integer)
    message: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)

class Comment(Base):
    __tablename__ = "review_comments"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(ForeignKey("recon_jobs.id"), index=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("model_result_versions.id"))
    author: Mapped[str] = mapped_column(String(64))
    body: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=now)