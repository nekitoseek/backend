# модель User (sqlalchemy)
from sqlalchemy import Column, Integer, String, ForeignKey, Text, TIMESTAMP, DateTime
from sqlalchemy.orm import declarative_base, relationship
from datetime import datetime

Base = declarative_base()

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    username = Column(String(50), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(100), nullable=False)
    email = Column(String(100), unique=True, nullable=False)
    telegram_id = Column(String(100), nullable=True)
    registration_date = Column(TIMESTAMP, default=datetime.utcnow)

class Group(Base):
    __tablename__ = "groups"
    id = Column(Integer, primary_key=True)
    name = Column(String(20), unique=True, nullable=False)

class Discipline(Base):
    __tablename__ = "disciplines"
    id = Column(Integer, primary_key=True)
    name = Column(String(100), unique=True, nullable=False)

class StudentGroup(Base):
    __tablename__ = "student_groups"
    student_id = Column(Integer, ForeignKey("users.id"), primary_key=True)
    group_id = Column(Integer, ForeignKey("groups.id"), nullable=False)

class Queue(Base):
    __tablename__ = "queues"
    id = Column(Integer, primary_key=True)
    title = Column(String(100), nullable=False)
    description = Column(Text)
    created_at = Column(DateTime(timezone=True), default=datetime.utcnow)
    scheduled_date = Column(DateTime(timezone=True), nullable=False)
    scheduled_end = Column(DateTime(timezone=True), nullable=False)
    status = Column(String(10), nullable=False) # 'active' or 'closed'
    creator_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    discipline_id = Column(Integer, ForeignKey("disciplines.id"), nullable=False)

    groups = relationship("Group", secondary="queue_groups", backref="queues")
    discipline = relationship("Discipline")
    creator = relationship("User", foreign_keys=[creator_id])

class QueueGroup(Base):
    __tablename__ = "queue_groups"
    queue_id = Column(Integer, ForeignKey("queues.id"), primary_key=True)
    group_id = Column(Integer, ForeignKey("groups.id"), primary_key=True)

class QueueParticipant(Base):
    __tablename__ = "queue_participants"
    id = Column(Integer, primary_key=True)
    queue_id = Column(Integer, ForeignKey("queues.id"), nullable=False)
    student_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    position = Column(Integer, nullable=False)
    joined_at = Column(TIMESTAMP, default=datetime.utcnow)
    status = Column(String(10), nullable=False) # 'waiting', 'current', 'done'

class Notification(Base):
    __tablename__ = "notifications"
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    message_text = Column(Text, nullable=False)
    sent_at = Column(TIMESTAMP, default=datetime.utcnow)
    status = Column(String(10), nullable=False) # 'sent', 'read', 'error'