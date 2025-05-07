# схемы (pydantic)
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from datetime import datetime

# схемы для авторизации
class Token(BaseModel):
    access_token: str
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


# создание очереди
class QueueCreate(BaseModel):
    title: str
    description: Optional[str]
    scheduled_date: datetime
    discipline_id: int
    group_ids: List[int]

class QueueOut(BaseModel):
    id: int
    title: str
    description: Optional[str]
    scheduled_date: datetime
    status: str
    creator_id: int
    discipline_id: int
    participants: Optional[List[QueueParticipantOut]]

    class Config:
        from_attributes = True


# редактирование очереди
class QueueUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    scheduled_date: Optional[datetime] = None
    discipline_id: Optional[int] = None
    group_ids: Optional[List[int]] = None



class NotificationOut(BaseModel):
    id: int
    message_text: str
    sent_at: datetime
    status: str

    class Config:
        orm_mode = True