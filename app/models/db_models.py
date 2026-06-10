import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Boolean, Float, ForeignKey, text
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


class User(Base):
    __tablename__ = "users"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        default=uuid.uuid4
    )
    email = Column(String, unique=True, nullable=False, index=True)
    hashed_password = Column(String, nullable=False)
    garmin_username = Column(String, nullable=True)
    garmin_password_encrypted = Column(String, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=text("now()"),
        default=datetime.utcnow
    )

    # Relationships
    metrics = relationship("Metric", back_populates="user", cascade="all, delete-orphan")
    insights = relationship("Insight", back_populates="user", cascade="all, delete-orphan")
    profile_snapshots = relationship("ProfileSnapshot", back_populates="user", cascade="all, delete-orphan")


class Metric(Base):
    __tablename__ = "metrics"

    # Composite primary key for hypertable support in SQLAlchemy
    time = Column(DateTime(timezone=True), primary_key=True, nullable=False)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False
    )
    metric = Column(String, primary_key=True, nullable=False)
    value = Column(JSONB, nullable=False)

    user = relationship("User", back_populates="metrics")


class Insight(Base):
    __tablename__ = "insights"

    id = Column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
        default=uuid.uuid4
    )
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False
    )
    metric = Column(String, nullable=False)
    insight = Column(String, nullable=False)
    anomaly_detected = Column(Boolean, server_default=text("false"), default=False)
    deviation_pct = Column(Float, nullable=True)
    created_at = Column(
        DateTime(timezone=True),
        server_default=text("now()"),
        default=datetime.utcnow
    )

    user = relationship("User", back_populates="insights")


class ProfileSnapshot(Base):
    __tablename__ = "profile_snapshots"

    # Composite primary key for hypertable support in SQLAlchemy
    time = Column(DateTime(timezone=True), primary_key=True, nullable=False)
    user_id = Column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
        nullable=False
    )
    fatigue_score = Column(Float, nullable=True)
    recovery_score = Column(Float, nullable=True)
    notes = Column(String, nullable=True)

    user = relationship("User", back_populates="profile_snapshots")
