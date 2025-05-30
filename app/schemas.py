# схемы (pydantic)
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime, timedelta, timezone

from app.models import Group


# схемы для авторизации
class Token(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str

class TokenData(BaseModel):
    username: Optional[str] = None

class UserLogin(BaseModel):
    username: str
    password: str

# регистрация пользователя
class UserCreate(BaseModel):
    username: str
    password: str
    full_name: str
    email: EmailStr
    group_id: int

class UserOut(BaseModel):
    id: int
    username: str
    full_name: str
    email: EmailStr
    telegram_id: Optional[str]
    registration_date: datetime

    class Config:
        orm_mode = True

class TelegramReset(BaseModel):
    telegram_id: str

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    email: Optional[EmailStr] = None
    password: Optional[str] = None
    group_id: Optional[int] = None
    telegram_id: Optional[str] = None


# список студентов в очереди
class QueueParticipantOut(BaseModel):
    id: int
    queue_id: int
    student_id: int
    position: int
    joined_at: datetime
    status: str

    class Config:
        orm_mode = True

class StudentInQueueOut(BaseModel):
    id: int
    full_name: str
    status: str
    joined_at: datetime
    group: str

    class Config:
        orm_mode = False

# создание очереди
class QueueCreate(BaseModel):
    title: str
    description: Optional[str]
    scheduled_date: datetime
    scheduled_end: datetime
    discipline_id: int
    group_ids: List[int]

# вывод групп
class GroupOut(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True

class DisciplineOut(BaseModel):
    id: int
    name: str

    class Config:
        from_attributes = True

class CreatorOut(BaseModel):
    id: int
    username: str
    full_name: str

    class Config:
        from_attributes = True

class QueueOut(BaseModel):
    id: int
    title: str
    description: Optional[str]
    created_at: datetime
    scheduled_date: datetime
    scheduled_end: datetime
    status: str
    creator_id: int
    creator: CreatorOut
    discipline_id: int
    groups: List[GroupOut]
    discipline: DisciplineOut

    class Config:
        from_attributes = True


# редактирование очереди
class QueueUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    scheduled_date: Optional[datetime] = None
    scheduled_end: Optional[datetime] = None
    discipline_id: Optional[int] = None
    group_ids: Optional[List[int]] = None


class NotificationOut(BaseModel):
    id: int
    message_text: str
    sent_at: datetime
    status: str

    class Config:
        from_attributes = True