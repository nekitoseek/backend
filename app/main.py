from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi import Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from app import crud, schemas
from app.database import get_db
from app.schemas import QueueCreate, QueueOut, UserOut
from app.crud import create_queue, get_queues
from app import auth
from app.schemas import UserLogin, Token
from app.models import User
from app.auth import get_current_user
from typing import List, Optional

app = FastAPI()

# Разрешаем доступ с фронта
origins = ["http://localhost:5173"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "Backend работает!"}


# регистрация
@app.post("/register", response_model=schemas.UserOut)
async def register_user(user: schemas.UserCreate, db: AsyncSession = Depends(get_db)):
    return await crud.create_user(db, user)

from fastapi.security import OAuth2PasswordRequestForm


# авторизация
@app.post("/login", response_model=Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db)
):
    db_user = await auth.authenticate_user(db, form_data.username, form_data.password)
    if not db_user:
        raise HTTPException(status_code=400, detail="Неверный логин или пароль")

    access_token = auth.create_access_token(data={"sub": str(db_user.id)})
    return {"access_token": access_token, "token_type": "bearer"}


# проверка роли пользователя
@app.get("/me")
async def read_current_user(current_user: User = Depends(get_current_user)):
    return {"username": current_user.username, "role": current_user.role}


# создание очереди
@app.post("/queues", response_model=QueueOut)
async def create_queue_route(
        queue: QueueCreate,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    if current_user.role != "teacher":
        raise HTTPException(status_code=403, detail="Только преподаватели могут создавать очереди")
    return await create_queue(db, queue, teacher_id=current_user.id)


# просмотр активных очередей
@app.get("/queues", response_model=List[QueueOut])
async def get_queues_route(
    group_id: Optional[int] = None,
    discipline_id: Optional[int] = None,
    status: str = "active",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    return await get_queues(db, group_id, discipline_id, status)

# удаление очереди (только владелец)
@app.delete("/queues/{queue_id}")
async def delete_queue_route(
        queue_id: int,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    return await crud.delete_queue(db, queue_id, current_user)


# редактирование очереди (только владелец)
@app.patch("/queues/{queue_id}", response_model=QueueOut)
async def update_queue_route(
        queue_id: int,
        queue_data: schemas.QueueUpdate,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    return await crud.queue_update(db, queue_id, queue_data, current_user)


# просмотр студентов в очереди
@app.get("/queues/{queue_id}/students", response_model=List[UserOut])
async def get_queue_students(
        queue_id: int,
        db: AsyncSession = Depends(get_db),
        current_user: User = Depends(get_current_user)
):
    return await crud.get_students_in_queue(db, queue_id)