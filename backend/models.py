from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import relationship
from datetime import datetime

try:
    from .database import Base
except ImportError:
    from database import Base

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(255), unique=True, index=True, nullable=False)
    hashed_password = Column(String(255), nullable=False)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationship to translations (one user can have many translations)
    translations = relationship("Translation", back_populates="user", cascade="all, delete-orphan")
    integrations = relationship("Integration", back_populates="owner", cascade="all, delete-orphan")
    internal_activities = relationship(
        "InternalTranslationActivity",
        back_populates="user",
        cascade="all, delete-orphan",
    )

class Translation(Base):
    __tablename__ = "translations"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    
    source_text = Column(Text, nullable=False)
    target_text = Column(Text, nullable=False)
    
    source_language = Column(String(10), nullable=False)
    target_language = Column(String(10), nullable=False)
    
    model_type = Column(String(50), nullable=False) # 'text' or 'voice'
    created_at = Column(DateTime, default=datetime.utcnow)

    # Relationship back to user
    user = relationship("User", back_populates="translations")


class Integration(Base):
    __tablename__ = "integrations"

    id = Column(Integer, primary_key=True, index=True)
    owner_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    name = Column(String(255), nullable=False)
    platform = Column(String(50), nullable=False)
    site_url = Column(String(500), nullable=False)
    webhook_url = Column(String(500), nullable=True)
    api_key_prefix = Column(String(32), unique=True, index=True, nullable=False)
    api_key_hash = Column(String(128), nullable=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)

    owner = relationship("User", back_populates="integrations")
    contents = relationship("ExternalContent", back_populates="integration", cascade="all, delete-orphan")
    jobs = relationship("TranslationJob", back_populates="integration", cascade="all, delete-orphan")


class ExternalContent(Base):
    __tablename__ = "external_contents"
    __table_args__ = (
        UniqueConstraint(
            "integration_id",
            "external_content_id",
            "target_language",
            name="uq_external_content_target",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    integration_id = Column(Integer, ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False)
    platform = Column(String(50), nullable=False)
    external_content_id = Column(String(255), nullable=False)
    content_type = Column(String(100), nullable=False)
    title = Column(String(500), nullable=True)
    source_language = Column(String(10), nullable=False)
    target_language = Column(String(10), nullable=False)
    content_format = Column(String(20), default="text")
    original_text = Column(Text, nullable=False)
    translated_text = Column(Text, nullable=True)
    status = Column(String(50), default="synced")
    metadata_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    integration = relationship("Integration", back_populates="contents")


class TranslationJob(Base):
    __tablename__ = "translation_jobs"

    id = Column(Integer, primary_key=True, index=True)
    integration_id = Column(Integer, ForeignKey("integrations.id", ondelete="CASCADE"), nullable=False)
    external_content_id = Column(Integer, ForeignKey("external_contents.id", ondelete="SET NULL"), nullable=True)
    status = Column(String(50), default="pending")
    source_language = Column(String(10), nullable=False)
    target_language = Column(String(10), nullable=False)
    content_format = Column(String(20), default="text")
    item_count = Column(Integer, default=0)
    completed_count = Column(Integer, default=0)
    error = Column(Text, nullable=True)
    callback_url = Column(String(500), nullable=True)
    result_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    integration = relationship("Integration", back_populates="jobs")


class UsageLog(Base):
    __tablename__ = "usage_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    integration_id = Column(Integer, ForeignKey("integrations.id", ondelete="SET NULL"), nullable=True)
    actor_type = Column(String(50), nullable=False)
    route = Column(String(255), nullable=False)
    provider = Column(String(100), nullable=False)
    model_type = Column(String(100), nullable=False)
    source_language = Column(String(10), nullable=False)
    target_language = Column(String(10), nullable=False)
    character_count = Column(Integer, default=0)
    estimated_tokens = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)


class InternalTranslationActivity(Base):
    __tablename__ = "internal_translation_activities"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    activity_type = Column(String(50), nullable=False)
    source_language = Column(String(10), nullable=False)
    target_languages = Column(Text, nullable=False)
    provider = Column(String(100), nullable=False)
    model = Column(String(100), nullable=True)
    character_count = Column(Integer, default=0)
    text_translation_count = Column(Integer, default=0)
    document_count = Column(Integer, default=0)
    excel_file_count = Column(Integer, default=0)
    excel_rows_translated = Column(Integer, default=0)
    source_filename = Column(String(500), nullable=True)
    output_filename = Column(String(500), nullable=True)
    download_mime_type = Column(String(255), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    user = relationship("User", back_populates="internal_activities")
