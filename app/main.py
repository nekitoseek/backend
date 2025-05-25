from fastapi import FastAPI, Depends, HTTPException, status, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import joinedload
from app import auth, crud, models, schemas, database
from typing import List, Optional

app = FastAPI()

def verify_admin(current_user: models.User):
    if current_user.username != "admin":
        raise HTTPException(status_code=403, detail="Нет прав администратора.")

# Доступ с фронта
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
    return {"id": current_user.id, "username": current_user.username, "email": current_user.email, "full_name": current_user.full_name}

@app.patch("/me", response_model=schemas.UserOut)
async def update_profile(
        data: schemas.UserUpdate,
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
    return await crud.update_user(db, current_user.id, data)

# api создания очереди
@app.post("/queues", response_model=schemas.QueueOut)
async def create_queue_route(
        queue: schemas.QueueCreate,
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
    return await crud.create_queue(db, queue, creator_id=current_user.id)

# api просмотр активных очередей
@app.get("/queues", response_model=List[schemas.QueueOut])
async def get_queues_route(
    group_id: Optional[int] = None,
    discipline_id: Optional[int] = None,
    status: Optional[str] = None,
    db: AsyncSession = Depends(database.get_db),
    current_user: models.User = Depends(auth.get_current_user)
):
    return await crud.get_queues(db, group_id, discipline_id, status)

# api для просмотра конкретной очереди
@app.get("/queues/{queue_id}", response_model=schemas.QueueOut)
async def get_queue_detail(
        queue_id: int,
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
    await crud.maybe_close_queue(db, queue_id)
    result = await db.execute(
        select(models.Queue)
        .options(
            joinedload(models.Queue.groups),
            joinedload(models.Queue.discipline),
            joinedload(models.Queue.creator)
        )
        .where(models.Queue.id == queue_id)
    )
    queue = result.scalars().first()

    if not queue:
        raise HTTPException(status_code=404, detail="Очередь не найдена")

    return schemas.QueueOut.from_orm(queue)

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
@app.get("/queues/{queue_id}/students", response_model=List[schemas.StudentInQueueOut])
async def get_queue_students(
        queue_id: int,
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
    await crud.maybe_close_queue(db, queue_id)
    await crud.maybe_start_queue(db, queue_id)
    return await crud.get_students_in_queue(db, queue_id)


# api для присоединения к очереди
@app.post("/queues/{queue_id}/join")
async def join_queue_route(
        queue_id: int,
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
    return await crud.join_queue(db, queue_id, current_user.id)

# api для покидания очереди
@app.post("/queues/{queue_id}/leave")
async def leave_queue_route(
        queue_id: int,
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
    return await crud.leave_queue(db, queue_id, current_user.id)


# api для закрытия очереди
@app.post("/queues/{queue_id}/close")
async def manual_close_queue_route(
        queue_id: int,
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
    return await crud.manual_close_queue(db, queue_id, current_user.id)

# api для завершения сдачи (конкретный студент)
@app.post("/queues/{queue_id}/complete")
async def complete_student_route(
        queue_id: int,
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
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


@app.get("/groups")
async def get_groups(
        db: AsyncSession = Depends(database.get_db)
):
    result = await db.execute(select(models.Group).order_by(models.Group.name))
    return result.scalars().all()

@app.get("/disciplines")
async def get_disciplines(db: AsyncSession = Depends(database.get_db)):
    result = await db.execute(select(models.Discipline).order_by(models.Discipline.name))
    return result.scalars().all()



###### ДЛЯ АДМИНИСТРАТОРА ######
@app.post("/admin/groups")
async def add_group_route(
        name: str = Body(...),
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
    verify_admin(current_user)
    return await crud.create_group(db, name)

@app.delete("/admin/groups/{group_id}")
async def delete_group(
        group_id: int,
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
    verify_admin(current_user)
    group = await db.get(models.Group, group_id)
    if not group:
        raise HTTPException(status_code=404, detail="Группа не найдена")
    await db.delete(group)
    await db.commit()
    return {"detail": "Группа удалена"}

@app.post("/admin/disciplines")
async def add_discipline_route(
        name: str = Body(...),
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
    verify_admin(current_user)
    return await crud.create_discipline(db, name)

@app.delete("/admin/disciplines/{discipline_id}")
async def delete_discipline(
        discipline_id: int,
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
    verify_admin(current_user)
    discipline = await db.get(models.Discipline, discipline_id)
    if not discipline:
        raise HTTPException(status_code=404, detail="Дисциплина не найдена")
    await db.delete(discipline)
    await db.commit()
    return {"detail": "Дисциплина удалена"}

@app.get("/admin/queues", response_model=List[schemas.QueueOut])
async def get_all_queues_admin(
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
    verify_admin(current_user)
    result = await db.execute(
        select(models.Queue)
        .options(
            joinedload(models.Queue.groups),
            joinedload(models.Queue.discipline),
            joinedload(models.Queue.creator)
        )
        .order_by(models.Queue.scheduled_date.desc())
    )
    return result.unique().scalars().all()

@app.delete("/admin/queues/{queue_id}")
async def delete_queue_admin(
        queue_id: int,
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
    verify_admin(current_user)
    return await crud.delete_queue_by_admin(db, queue_id)

@app.patch("/admin/queues/{queue_id}", response_model=schemas.QueueOut)
async def update_queue_admin(
        queue_id: int,
        data: schemas.QueueUpdate,
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
    verify_admin(current_user)
    return await crud.queue_update_admin(db, queue_id, data)

@app.post("/admin/queues/{queue_id}/force-close")
async def force_close_queue_admin(
        queue_id: int,
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
    verify_admin(current_user)
    result = await db.execute(
        select(models.Queue).where(models.Queue.id == queue_id)
    )
    queue = result.scalars().first()
    if not queue:
        raise HTTPException(status_code=404, detail="Очереди не найдена")
    queue.status = "closed"
    await db.commit()
    return {"detail": "Очередь принудительно закрыта"}