"""SQLAlchemy ORM models for all tables."""
import enum
from datetime import datetime

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import relationship

from database import Base


class SourceType(str, enum.Enum):
    website = "website"
    telegram_channel = "telegram_channel"


class RewriteStyle(str, enum.Enum):
    none = "none"
    light = "light"
    heavy = "heavy"


class PostStatus(str, enum.Enum):
    success = "success"
    failed = "failed"


class Source(Base):
    __tablename__ = "sources"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    type = Column(String(50), nullable=False)  # website | telegram_channel
    url = Column(String(500), nullable=False)
    fetch_interval_minutes = Column(Integer, nullable=False, default=60)
    rewrite_style = Column(String(20), nullable=False, default=RewriteStyle.light.value)
    language = Column(String(50), nullable=False, default="English")
    topic_keywords = Column(String(500), nullable=True, default="")
    persona = Column(String(500), nullable=True, default="")
    priority = Column(Integer, nullable=False, default=5)
    is_active = Column(Boolean, nullable=False, default=True)
    last_fetched_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    schedules = relationship("Schedule", back_populates="source", cascade="all, delete-orphan")
    posts = relationship("Post", back_populates="source", cascade="all, delete-orphan")

    def keyword_list(self):
        if not self.topic_keywords:
            return []
        return [k.strip() for k in self.topic_keywords.split(",") if k.strip()]


class Channel(Base):
    __tablename__ = "channels"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(255), nullable=False)
    telegram_id = Column(String(255), nullable=False)  # numeric id or @username
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    schedules = relationship("Schedule", back_populates="channel", cascade="all, delete-orphan")
    posts = relationship("Post", back_populates="channel", cascade="all, delete-orphan")


class Schedule(Base):
    __tablename__ = "schedules"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=False)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=False)
    cron_expression = Column(String(100), nullable=False)  # e.g. "*/30 * * * *"
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    source = relationship("Source", back_populates="schedules")
    channel = relationship("Channel", back_populates="schedules")


class Post(Base):
    __tablename__ = "posts"

    id = Column(Integer, primary_key=True, index=True)
    source_id = Column(Integer, ForeignKey("sources.id"), nullable=True)
    channel_id = Column(Integer, ForeignKey("channels.id"), nullable=True)
    original_text = Column(Text, nullable=True)
    rewritten_text = Column(Text, nullable=True)
    status = Column(String(20), nullable=False, default=PostStatus.success.value)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    source = relationship("Source", back_populates="posts")
    channel = relationship("Channel", back_populates="posts")


class BotSettings(Base):
    __tablename__ = "bot_settings"

    id = Column(Integer, primary_key=True, index=True)
    bot_enabled = Column(Boolean, nullable=False, default=True)
    rewrite_enabled = Column(Boolean, nullable=False, default=True)
    default_rewrite_style = Column(String(20), nullable=False, default=RewriteStyle.light.value)
    gemini_model = Column(String(100), nullable=False, default="gemini-flash-latest")
    max_posts_per_hour = Column(Integer, nullable=False, default=20)
    include_images = Column(Boolean, nullable=False, default=False)
    admin_username = Column(String(255), nullable=True)
    admin_password_hash = Column(String(255), nullable=True)
    admin_password_salt = Column(String(64), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
