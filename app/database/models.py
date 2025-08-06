# app/database/models.py
from sqlalchemy import (Column, Integer, String, Boolean, DateTime, 
Text, Enum, ForeignKey, UniqueConstraint, Float, JSON)
from sqlalchemy.ext.declarative import declarative_base
from datetime import datetime
import enum


Base = declarative_base()


class Proxy(Base):
    __tablename__ = "proxies"

    id = Column(Integer, primary_key=True, index=True)
    container_name = Column(String, unique=True, index=True)
    container_ip = Column(String)
    tor_exit_node = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)
    running = Column(Boolean, default=True)


class APIs(Base):
    __tablename__ = "apis"
    id = Column(Integer, primary_key=True, index=True)
    api_name = Column(String, unique=True, index=True)
    api_provider = Column(String)
    api_type = Column(String)
    api_key = Column(String)
    model = Column(String)
    prompt = Column(Text)
    max_tokens = Column(Integer)
    timestamp = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=False)


class BotPurpose(enum.Enum):
    SCRAPE_MARKETPLACE = "scrape_marketplace"
    SCRAPE_POST = "scrape_post"
    SCRAPE_PROFILE = "scrape_profile"


class BotProfile(Base):
    __tablename__ = "bot_profiles"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    password = Column(String, nullable=False)
    purpose = Column(Enum(BotPurpose), nullable=False)
    tor_proxy = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    session = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)


class OnionUrl(Base):
    __tablename__ = "onion_urls"

    id = Column(Integer, primary_key=True, index=True)
    url = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)


class MarketplacePaginationScan(Base):
    __tablename__ = "marketplace_pagination_scans"

    id = Column(Integer, primary_key=True, index=True)
    scan_name = Column(String, nullable=False)
    pagination_url = Column(String, nullable=False)
    max_page = Column(Integer, nullable=False)
    batches = Column(Text, nullable=True)
    timestamp = Column(DateTime, default=datetime.utcnow)


class ScanStatus(enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    STOPPED = "stopped"


class MarketplacePostScan(Base):
    __tablename__ = "marketplace_post_scans"

    id = Column(Integer, primary_key=True, index=True)
    scan_name = Column(String, nullable=False, unique=True)
    pagination_scan_name = Column(String, ForeignKey("marketplace_pagination_scans.scan_name"), nullable=False)
    start_date = Column(DateTime(timezone=True), default=datetime.utcnow)
    completion_date = Column(DateTime(timezone=True), nullable=True)
    status = Column(Enum(ScanStatus), default=ScanStatus.STOPPED, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)


class MarketplacePost(Base):
    __tablename__ = "marketplace_posts"

    id = Column(Integer, primary_key=True, index=True)
    scan_id = Column(Integer, ForeignKey("marketplace_post_scans.id"), nullable=False)
    timestamp = Column(String, nullable=False)
    title = Column(String, nullable=False)
    author = Column(String, nullable=False)
    link = Column(String, nullable=False)
    __table_args__ = (UniqueConstraint('scan_id', 'timestamp', name='uix_scan_timestamp'),)


class PostDetailScan(Base):
    __tablename__ = "post_detail_scans"

    id = Column(Integer, primary_key=True, index=True)
    scan_name = Column(String, nullable=False, unique=True)
    source_scan_name = Column(String, ForeignKey("marketplace_post_scans.scan_name"), nullable=False)
    start_date = Column(DateTime(timezone=True), default=datetime.utcnow)
    completion_date = Column(DateTime(timezone=True), nullable=True)
    status = Column(Enum(ScanStatus), default=ScanStatus.STOPPED, nullable=False)
    batch_size = Column(Integer, nullable=False)
    site_url = Column(String, nullable=False)
    timestamp = Column(DateTime, default=datetime.utcnow)


class MarketplacePostDetails(Base):
    __tablename__ = "marketplace_post_details"

    id = Column(Integer, primary_key=True, index=True)
    scan_id = Column(Integer, ForeignKey("post_detail_scans.id"), nullable=False)
    batch_name = Column(String, nullable=False)
    title = Column(String, nullable=False)
    content = Column(Text, nullable=False)
    timestamp = Column(String, nullable=False)
    author = Column(String, nullable=False)
    link = Column(String, nullable=False)
    original_language = Column(String, nullable=True)
    original_text = Column(Text, nullable=True)
    translated_language = Column(String, nullable=True)
    translated_text = Column(Text, nullable=True)
    is_translated = Column(Boolean, default=False)
    sentiment = Column(String, nullable=True)
    positive_score = Column(Float, nullable=True)
    negative_score = Column(Float, nullable=True)
    neutral_score = Column(Float, nullable=True)
    timestamp_added = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint('scan_id', 'timestamp', 'batch_name', name='uix_scan_timestamp_batch'),)


class Watchlist(Base):
    __tablename__ = "watchlists"

    id = Column(Integer, primary_key=True, index=True)
    target_name = Column(String, unique=True, index=True)
    profile_link = Column(String)
    priority = Column(String)
    frequency = Column(String)
    timestamp = Column(DateTime, default=datetime.utcnow)


class WatchlistProfileScan(Base):
    __tablename__ = "watchlist_profile_scans"
    id = Column(Integer, primary_key=True, index=True)
    watchlist_id = Column(Integer, ForeignKey("watchlists.id"), nullable=False)
    scan_timestamp = Column(DateTime, default=datetime.utcnow)
    profile_data = Column(JSON)

