# /app/main.py
from fastapi import FastAPI, Depends, HTTPException, status, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, or_
from sqlalchemy.orm import joinedload
from app import auth, crud, models, schemas, database
from typing import List, Optional

app = FastAPI()


def verify_admin(current_user: models.User):
    if not current_user.is_admin:
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

    if not db_user.is_active:
        raise HTTPException(status_code=403, detail="Пользователь заблокирован")

    access_token = auth.create_access_token(data={"sub": str(db_user.id)})
    refresh_token = auth.create_refresh_token(data={"sub": str(db_user.id)})
    return {"access_token": access_token, "refresh_token": refresh_token, "token_type": "bearer"}


@app.post("/refresh", response_model=schemas.Token)
async def refresh_token(refresh_token: str = Body(...)):
    try:
        payload = jwt.decode(refresh_token, auth.REFRESH_SECRET_KEY, algorithms=[auth.ALGORITHM])
        user_id = int(payload.get("sub"))
        new_access_token = auth.create_access_token(data={"sub": str(user_id)})
        return {
            "access_token": new_access_token,
            "refresh_token": refresh_token,
            "token_type": "bearer"
        }
    except JWTError:
        raise HTTPException(status_code=401, detail="Недействительный refresh token")


@app.post("/reset-telegram")
async def reset_telegram_id(data: schemas.TelegramReset, db: AsyncSession = Depends(database.get_db)):
    await db.execute(
        update(models.User).where(models.User.telegram_id == data.telegram_id).values(telegram_id=None)
    )
    await db.commit()
    return {"detail": "Telegram ID сброшен"}


# api для проверки роли пользователя
@app.get("/me")
async def read_current_user(current_user: models.User = Depends(auth.get_current_user)):
    return current_user


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
        # group_id: Optional[int] = None,
        discipline_id: Optional[int] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
    return await crud.get_queues(db, discipline_id, status, search, current_user)

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
        search: Optional[str] = None,
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
    verify_admin(current_user)
    return await crud.get_admin_queues(db, None, None, 'all', search)


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


@app.get("/admin/users", response_model=List[schemas.UserOut])
async def get_users(
        search: Optional[str] = None,
        group: Optional[str] = None,
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
    verify_admin(current_user)

    query = (select(models.User)
    .options(joinedload(models.User.group))
    .join(models.StudentGroup, models.StudentGroup.student_id == models.User.id)
    .join(models.Group, models.StudentGroup.group_id == models.Group.id))

    if search:
        query = query.where(
            or_(
                models.User.username.ilike(f"%{search}%"),
                models.User.full_name.ilike(f"%{search}%"),
                models.User.email.ilike(f"%{search}%"),
                models.Group.name.ilike(f"%{search}%"),
            )
        )

    result = await db.execute(query)
    return result.scalars().all()


@app.patch("/admin/users/{user_id}", response_model=schemas.UserOut)
async def update_user_admin(
        user_id: int,
        data: schemas.UserUpdate,
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
    verify_admin(current_user)
    await crud.update_user(db, user_id, data)

    result = await db.execute(
        select(models.User).options(joinedload(models.User.group)).where(models.User.id == user_id)
    )
    return result.scalars().first()


@app.post("/admin/users/{user_id}/set-admin")
async def set_user_admin(
        user_id: int,
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
    verify_admin(current_user)
    user = await db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    user.is_admin = True
    await db.commit()
    return {"detail": f"Пользователь {user.username} назначен администратором"}


@app.post("/admin/users/{user_id}/ban")
async def ban_user(
        user_id: int,
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
    verify_admin(current_user)
    user = await db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    user.is_active = False
    await db.commit()
    return {"detail": f"Пользователь {user.username} заблокирован"}


@app.post("/admin/users/{user_id}/unban")
async def ban_user(
        user_id: int,
        db: AsyncSession = Depends(database.get_db),
        current_user: models.User = Depends(auth.get_current_user)
):
    verify_admin(current_user)
    user = await db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")
    user.is_active = True
    await db.commit()
    return {"detail": f"Пользователь {user.username} разблокирован"}
