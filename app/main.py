from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app import auth, crud, models, schemas, database
from typing import List, Optional

app = FastAPI()

@app.get("/")
async def root():
    return {"message": "Backend работает!"}

# api регистрации
@app.post("/register", response_model=schemas.UserOut)
async def register_user(user: schemas.UserCreate, db: AsyncSession = Depends(database.get_db)):
    return await crud.create_user(db, user)

# api авторизации
@app.post("/login", response_model=schemas.Token)
async def login(
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(database.get_db)
):
    db_user = await auth.authenticate_user(db, form_data.username, form_data.password)
    if not db_user:
        raise HTTPException(status_code=400, detail="Неверный логин или пароль")

    access_token = auth.create_access_token(data={"sub": str(db_user.id)})
    return {"access_token": access_token, "token_type": "bearer"}

# api для проверки роли пользователя
@app.get("/me")
async def read_current_user(current_user: models.User = Depends(auth.get_current_user)):
    return {"username": current_user.username, "role": current_user.role}

# api создания очереди
@app.post("/queues", response_model=schemas.QueueOut)
async def create_queue_route(
        queue: schemas.QueueCreate,
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
    if current_user.role != "teacher":
        raise HTTPException(status_code=403, detail="Только преподаватели могут создавать очереди")
    return await crud.create_queue(db, queue, teacher_id=current_user.id)

# api просмотр активных очередей
@app.get("/queues", response_model=List[schemas.QueueOut])
async def get_queues_route(
    group_id: Optional[int] = None,
    discipline_id: Optional[int] = None,
    status: str = "active",
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    return await crud.get_queues(db, group_id, discipline_id, status)

# api для удаления очереди (только владелец)
@app.delete("/queues/{queue_id}")
async def delete_queue_route(
        queue_id: int,
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
    return await crud.delete_queue(db, queue_id, current_user)

# api для редактирования очереди (только владелец)
@app.patch("/queues/{queue_id}", response_model=schemas.QueueOut)
async def update_queue_route(
        queue_id: int,
        queue_data: schemas.QueueUpdate,
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
    return await crud.queue_update(db, queue_id, queue_data, current_user)


# api для просмотра студентов в очереди
@app.get("/queues/{queue_id}/students", response_model=List[schemas.UserOut])
async def get_queue_students(
        queue_id: int,
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
    return await crud.get_students_in_queue(db, queue_id)


# api для присоединения к очереди
@app.post("/queues/{queue_id}/join")
async def join_queue_route(
        queue_id: int,
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
    if current_user.role != "student":
        raise HTTPException(status_code=403, detail="Только студенты могут вставать в очереди")
    return await crud.join_queue(db, queue_id, current_user.id)

# api для покидания очереди
@app.post("/queues/{queue_id}/leave")
async def leave_queue_route(
        queue_id: int,
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
    if current_user.role != "student":
        raise HTTPException(status_code=403, detail="Только студенты могут покидать очередь")

    return await crud.leave_queue(db, queue_id, current_user.id)

# api для вызова следующего
@app.post("/queues/{queue_id}/call")
async def call_next_student_route(
        queue_id: int,
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
    if current_user.role != "teacher":
        raise HTTPException(status_code=403, detail="Только преподаватели могут вызывать студентов")
    return await crud.call_next_student(db, queue_id, current_user.id)

# api для закрытия очереди
@app.post("/queues/{queue_id}/close")
async def close_queue_route(
        queue_id: int,
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
    if current_user.role != "teacher":
        raise HTTPException(status_code=403, detail="Только преподаватели могут закрывать очередь")

    return await crud.close_queue(db, queue_id, current_user.id)

# api для завершения сдачи (конкретный студент)
@app.post("/queues/{queue_id}/complete")
async def complete_student_route(
        queue_id: int,
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
    if current_user.role != "teacher":
        raise HTTPException(status_code=403, detail="Только преподаватели могут завершать вызов")
    return await crud.complete_current_student(db, queue_id, current_user.id)

# api для уведомлений (просто с бд пока что)
@app.get("/notifications", response_model=List[schemas.NotificationOut])
async def get_my_notifications(
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
    result = await db.execute(
        select(models.Notification).where(models.Notification.user_id == current_user.id)
    )
    return result.scalars().all()



# Разрешаем доступ с фронта
# origins = ["http://localhost:5173"]
# app.add_middleware(
#     CORSMiddleware,
#     allow_origins=origins,
#     allow_credentials=True,
#     allow_methods=["*"],
#     allow_headers=["*"],
# )