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
    role: str

class UserOut(BaseModel):
    id: int
    username: str
    full_name: str
    email: EmailStr
    role: str
    telegram_id: Optional[str]
    registration_date: datetime

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
    teacher_id: int
    discipline_id: int

    class Config:
        from_attributes = True


# редактирование очереди
class QueueUpdate(BaseModel):
    title: Optional[str] = None
    description: Optional[str] = None
    scheduled_date: Optional[datetime] = None
    discipline_id: Optional[int] = None
    group_ids: Optional[List[int]] = None