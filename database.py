"""
database.py - SQLite Database & Persistence Layer
Uses SQLAlchemy with SQLite (zero configuration, single local file: interview.db).
"""
import json
import uuid
from datetime import datetime
from typing import Optional, Dict, Any, List

from sqlalchemy import create_engine, Column, String, Integer, Text, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, sessionmaker, relationship, Session

DATABASE_URL = "sqlite:///./interview.db"

# connect_args={"check_same_thread": False} is required for SQLite with FastAPI multi-threaded requests
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


class Interview(Base):
    __tablename__ = "interviews"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    status = Column(String, default="CREATED")  # CREATED, IN_PROGRESS, COMPLETED, FAILED
    github_username = Column(String, nullable=True)
    selected_repo = Column(String, nullable=True)
    github_metadata = Column(Text, nullable=True)  # JSON-serialized repo & profile data
    score = Column(Integer, nullable=True)
    feedback = Column(Text, nullable=True)
    evaluation_data = Column(Text, nullable=True)  # JSON-serialized 4-pillar scorecard
    created_at = Column(DateTime, default=datetime.utcnow)

    messages = relationship("Message", back_populates="interview", cascade="all, delete-orphan")

    def get_github_metadata(self) -> Optional[Dict[str, Any]]:
        return json.loads(self.github_metadata) if self.github_metadata else None

    def set_github_metadata(self, data: Dict[str, Any]):
        self.github_metadata = json.dumps(data)

    def get_evaluation_data(self) -> Optional[Dict[str, Any]]:
        return json.loads(self.evaluation_data) if self.evaluation_data else None

    def set_evaluation_data(self, data: Dict[str, Any]):
        self.evaluation_data = json.dumps(data)


class Message(Base):
    __tablename__ = "messages"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    interview_id = Column(String, ForeignKey("interviews.id"), nullable=False)
    sender = Column(String, nullable=False)  # "User" or "Assistant"
    text = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    interview = relationship("Interview", back_populates="messages")


# Initialize tables automatically on startup
Base.metadata.create_all(bind=engine)


def get_db():
    """Dependency helper providing a database session per request."""
    db: Session = SessionLocal()
    try:
        yield db
    finally:
        db.close()
