# /app/crud.py
from fastapi import HTTPException
from sqlalchemy import delete, func, update, select, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from passlib.hash import bcrypt
from datetime import datetime, timezone, timedelta
from typing import List, Optional
from app import models, schemas
from app.models import QueueParticipant
from app.schemas import QueueUpdate
from app.telegram_utils import notify_telegram_user
import httpx
import asyncio


# создание пользователя
async def create_user(db: AsyncSession, user: schemas.UserCreate):
    # проверка, логин или email уже существуют
    result = await db.execute(select(models.User).where(models.User.username == user.username))
    if result.scalars().first():
        raise HTTPException(status_code=400, detail="Пользователь с таким логином уже существует")

    result = await db.execute(select(models.User).where(models.User.email == user.email))
    if result.scalars().first():
        raise HTTPException(status_code=400, detail="Пользователь с таким email уже существует")

    hashed_password = bcrypt.hash(user.password)
    db_user = models.User(
        username=user.username,
        password_hash=hashed_password,
        full_name=user.full_name,
        email=user.email,
    )
    db.add(db_user)
    await db.flush()

    db.add(models.StudentGroup(student_id=db_user.id, group_id=user.group_id))

    await db.commit()

    result = await db.execute(
        select(models.User)
        .options(joinedload(models.User.group))
        .where(models.User.id == db_user.id)
    )
    user_with_group = result.scalar_one()
    return user_with_group


async def update_user(db: AsyncSession, user_id: int, data: schemas.UserUpdate):
    user = await db.get(models.User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="Пользователь не найден")

    update_data = data.dict(exclude_unset=True)

    if "password" in update_data:
        update_data["password_hash"] = bcrypt.hash(update_data.pop("password"))

    for key, value in update_data.items():
        setattr(user, key, value)

    if "group_id" in update_data:
        await db.execute(
            delete(models.StudentGroup).where(models.StudentGroup.student_id == user_id)
        )
        db.add(models.StudentGroup(student_id=user.id, group_id=update_data["group_id"]))

    await db.commit()
    await db.refresh(user)
    return user


# создание очереди
async def create_queue(db: AsyncSession, queue: schemas.QueueCreate, creator_id: int):
    now = datetime.now(timezone.utc)
    scheduled = queue.scheduled_date.replace(tzinfo=timezone.utc)
    scheduled_end = queue.scheduled_end.replace(tzinfo=timezone.utc)

    if scheduled_end < scheduled:
        raise HTTPException(status_code=400, detail="Дата окончания не может быть раньше даты начала")

    if scheduled - now > timedelta(days=1):
        raise HTTPException(status_code=400, detail="Очередь можно создать не ранее, чем за 1 день до начала сдачи")

    if scheduled <= now < scheduled_end:
        status = "active"
    elif now < scheduled:
        status = "upcoming"
    else:
        status = "closed"

    new_queue = models.Queue(
        title=queue.title,
        description=queue.description,
        scheduled_date=queue.scheduled_date,
        scheduled_end=queue.scheduled_end,
        created_at=now,
        status=status,
        creator_id=creator_id,
        discipline_id=queue.discipline_id
    )

    existing_query = (
        select(models.Queue)
        .join(models.QueueGroup)
        .where(models.Queue.scheduled_date == queue.scheduled_date)
        .where(models.Queue.scheduled_end == queue.scheduled_end)
        .where(models.Queue.discipline_id == queue.discipline_id)
        .where(models.QueueGroup.group_id.in_(queue.group_ids))
    )
    existing_result = await db.execute(existing_query)

    if existing_result.scalars().first():
        raise HTTPException(status_code=400, detail="Такая очередь уже существует")

    db.add(new_queue)
    await db.flush()  # получаем ID новой очереди

    # Привязка групп к очереди
    for group_id in set(queue.group_ids):
        db.add(models.QueueGroup(queue_id=new_queue.id, group_id=group_id))

    await db.commit()
    await db.refresh(new_queue)

    # Подготовка данных для рассылки
    result = await db.execute(
        select(models.User.telegram_id)
        .join(models.StudentGroup, models.StudentGroup.student_id == models.User.id)
        .where(models.StudentGroup.group_id.in_(queue.group_ids))
        .where(models.User.telegram_id != None)
    )
    tg_ids = [row[0] for row in result.fetchall()]

    group_result = await db.execute(
        select(models.Group.name).where(models.Group.id.in_(queue.group_ids))
    )
    group_names = [row[0] for row in group_result.fetchall()]
    group_text = ", ".join(group_names)

    discipline_result = await db.execute(
        select(models.Discipline.name).where(models.Discipline.id == queue.discipline_id)
    )
    discipline_name = discipline_result.scalar() or "—"

    message = (
        f"📢 *Новая очередь!*\n\n"
        f"*Название:* {new_queue.title}\n"
        f"*Дисциплина:* {discipline_name}\n"
        f"*Время:* {new_queue.scheduled_date.strftime('%d.%m %H:%M')} – {new_queue.scheduled_end.strftime('%d.%m %H:%M')}\n"
        f"*Группы:* {group_text}\n\n"
        f"Нажмите кнопку ниже, чтобы записаться."
    )

    async def send_notifications(tg_ids, message, queue_id):
        for tg_id in tg_ids:
            await notify_telegram_user(tg_id, message, queue_id=queue_id, button="join")
            await asyncio.sleep(0.5)

    asyncio.create_task(send_notifications(tg_ids, message, queue_id=new_queue.id))

    result = await db.execute(
        select(models.Queue)
        .options(
            joinedload(models.Queue.groups),
            joinedload(models.Queue.discipline)
        )
        .where(models.Queue.id == new_queue.id)
    )
    return result.scalars().first()


# просмотр очередей
async def get_queues(
        db: AsyncSession,
        # group_id: Optional[int] = None,
        discipline_id: Optional[int] = None,
        status: Optional[str] = 'active',
        search: Optional[str] = None,
        current_user: models.User = None
) -> List[models.Queue]:
    now = datetime.now(timezone.utc)

    await db.execute(
        update(models.Queue)
        .where(models.Queue.status == "active")
        .where(models.Queue.scheduled_end <= now)
        .values(status="closed")
    )
    await db.commit()

    group_ids_result = await db.execute(
        select(models.StudentGroup.group_id)
        .where(models.StudentGroup.student_id == current_user.id)
    )
    user_group_ids = [row[0] for row in group_ids_result.fetchall()]

    query = select(models.Queue).options(
        joinedload(models.Queue.groups),
        joinedload(models.Queue.discipline),
        joinedload(models.Queue.creator)
    ).join(models.QueueGroup).where(models.QueueGroup.group_id.in_(user_group_ids))

    if status == "active":
        query = query.where(models.Queue.status == "active")
    elif status == "closed":
        query = query.where(models.Queue.status == "closed")
    elif status == "upcoming":
        query = query.where(models.Queue.status == "upcoming")
    elif status == "all":
        pass
    elif status:
        raise HTTPException(status_code=400, detail="Недопустимый статус")

    if discipline_id:
        query = query.where(models.Queue.discipline_id == discipline_id)
    if search:
        search_like = f"%{search.lower()}%"
        query = query.join(models.Discipline).join(models.Group).where(
            or_(
                func.lower(models.Queue.title).ilike(search_like),
                func.lower(models.Discipline.name).ilike(search_like),
                func.lower(models.Group.name).ilike(search_like),
            )
        )

    result = await db.execute(query)
    return result.unique().scalars().all()


# удаление очереди
async def delete_queue(db: AsyncSession, queue_id: int, current_user: models.User):
    result = await db.execute(select(models.Queue).where(models.Queue.id == queue_id))
    queue = result.scalars().first()
    if not queue:
        raise HTTPException(status_code=404, detail="Очередь не найдена")
    if queue.creator_id != current_user.id:
        raise HTTPException(status_code=403, detail="Нет прав на удаление этой очереди")
    await db.execute(delete(models.QueueGroup).where(models.QueueGroup.queue_id == queue_id))
    await db.delete(queue)
    await db.commit()
    return {"detail": "Очередь удалена"}


# редактирование очереди
async def queue_update(
        db: AsyncSession,
        queue_id: int,
        queue_data: schemas.QueueUpdate,
        current_user: models.User
):
    queue = await db.get(models.Queue, queue_id)
    if not queue:
        raise HTTPException(status_code=404, detail="Очередь не найдена")
    if queue.creator_id != current_user.id:
        raise HTTPException(status_code=403, detail="Нет прав на изменение этой очереди")

    update_data = queue_data.dict(exclude_unset=True)

    for field, value in update_data.items():
        if field != "group_ids":
            setattr(queue, field, value)

    if "group_ids" in update_data:
        await db.execute(
            delete(models.QueueGroup).where(models.QueueGroup.queue_id == queue_id)
        )
        for group_id in set(update_data["group_ids"]):
            db.add(models.QueueGroup(queue_id=queue_id, group_id=group_id))

    await db.commit()
    await db.refresh(queue)
    return queue


# просмотр студентов в очереди
async def get_students_in_queue(db: AsyncSession, queue_id: int):
    result = await db.execute(
        select(models.User.id, models.User.full_name, models.QueueParticipant.status, models.QueueParticipant.joined_at,
               models.Group.name.label("group_name"))
        .join(models.QueueParticipant, models.QueueParticipant.student_id == models.User.id)
        .join(models.StudentGroup, models.StudentGroup.student_id == models.User.id)
        .join(models.Group, models.Group.id == models.StudentGroup.group_id)
        .where(models.QueueParticipant.queue_id == queue_id)
        .order_by(models.QueueParticipant.position)
    )
    rows = result.fetchall()
    return [
        {
            "id": row[0],
            "full_name": row[1],
            "status": row[2],
            "joined_at": row[3],
            "group": row[4],
        }
        for row in rows
    ]


# запись в очередь
async def join_queue(db: AsyncSession, queue_id: int, student_id: int):
    result = await db.execute(
        select(models.Queue).where(models.Queue.id == queue_id)
    )
    queue = result.scalars().first()
    if not queue:
        raise HTTPException(status_code=404, detail="Очередь не найдена")

    now = datetime.now(timezone.utc)
    if queue.status == "closed":
        raise HTTPException(status_code=403, detail="Очередь завершена, запись невозможна")

    # проверка на принадлежность студента группе, для которой создана очередь
    result = await db.execute(
        select(models.QueueGroup.group_id)
        .where(models.QueueGroup.queue_id == queue_id)
    )
    allowed_group_ids = {row[0] for row in result.fetchall()}
    result = await db.execute(
        select(models.StudentGroup.group_id)
        .where(models.StudentGroup.student_id == student_id)
    )
    student_group_ids = {row[0] for row in result.fetchall()}
    if not allowed_group_ids & student_group_ids:
        raise HTTPException(status_code=403, detail="Ваша группа не участвует в этой очереди")

    # проверка есть ли студент уже в очереди
    result = await db.execute(
        select(models.QueueParticipant).where(
            models.QueueParticipant.queue_id == queue_id,
            models.QueueParticipant.student_id == student_id,
        )
    )
    existing = result.scalars().first()
    if existing:
        raise HTTPException(status_code=400, detail="Студент уже в очереди")

    # вычисление позиции в очереди
    result = await db.execute(
        select(func.max(models.QueueParticipant.position)).where(
            models.QueueParticipant.queue_id == queue_id,
        )
    )
    max_position = result.scalar() or 0

    is_first = (max_position == 0)

    new_participant = models.QueueParticipant(
        queue_id=queue_id,
        student_id=student_id,
        position=max_position + 1,
        status="current" if is_first and queue.status == "active" else "waiting"
    )

    db.add(new_participant)
    await db.commit()
    await db.refresh(new_participant)

    if is_first and queue.status == "active":
        user = await db.get(models.User, student_id)
        if user and user.telegram_id:
            asyncio.create_task(
                notify_telegram_user(
                    telegram_id=user.telegram_id,
                    message=f"Название очереди: {queue.title}.\nСейчас ваша очередь сдавать. Удачи!",
                    queue_id=queue_id,
                    button="complete"
                )
            )
    return new_participant


# покидание очереди
async def leave_queue(db: AsyncSession, queue_id: int, student_id: int):
    result = await db.execute(
        select(models.QueueParticipant).where(
            models.QueueParticipant.queue_id == queue_id,
            models.QueueParticipant.student_id == student_id
        )
    )
    participant = result.scalars().first()
    if not participant:
        raise HTTPException(status_code=404, detail="Вы не состоите в этой очереди")

    await db.delete(participant)
    await db.commit()
    return {"detail": "Вы покинули очередь"}


# сдача завершена
async def complete_current_student(db: AsyncSession, queue_id: int, user_id: int):
    result = await db.execute(select(models.Queue).where(models.Queue.id == queue_id))
    queue = result.scalars().first()
    now = datetime.now(timezone.utc)
    if queue.status != "active":
        raise HTTPException(status_code=403, detail="Очередь не активна")
    if now < queue.scheduled_date:
        raise HTTPException(status_code=403, detail="Очередь еще не началась")

    result = await db.execute(
        select(models.QueueParticipant)
        .where(models.QueueParticipant.queue_id == queue_id)
        .order_by(models.QueueParticipant.position.asc())
    )
    participants = result.scalars().all()
    if not participants:
        raise HTTPException(status_code=404, detail="Очередь пуста")

    current_participant = next((p for p in participants if p.status == "current"), None)
    if not current_participant or current_participant.student_id != user_id:
        raise HTTPException(status_code=403, detail="Вы не сдающий участник")

    current_participant.status = "done"

    for p in participants[1:]:
        if p.status == "waiting":
            p.status = "current"
            next_student = await db.get(models.User, p.student_id)
            if next_student and next_student.telegram_id:
                await notify_telegram_user(
                    telegram_id=next_student.telegram_id,
                    message=f"Название очереди: {queue.title}.\nСейчас ваша очередь сдавать. Удачи!",
                    queue_id=queue.id,
                    button="complete"
                )
            break

    await db.commit()
    return {"detail": "Сдача завершена"}


# уведомления
async def send_notification(db: AsyncSession, user_id: int, message_text: str):
    notification = models.Notification(
        user_id=user_id,
        message_text=message_text,
        status="sent"
    )
    db.add(notification)
    await db.commit()


async def get_notifications_for_user(db: AsyncSession, user_id: int):
    result = await db.execute(
        select(models.Notification).where(models.Notification.user_id == user_id)
    )
    return result.scalars().all()


# старт очереди по времени
async def maybe_start_queue(db: AsyncSession, queue_id: int):
    result = await db.execute(select(models.Queue).where(models.Queue.id == queue_id))
    queue = result.scalars().first()
    if not queue or queue.status != "upcoming":
        return

    now = datetime.now(timezone.utc)
    if now >= queue.scheduled_date and now < queue.scheduled_end:
        result = await db.execute(
            select(models.QueueParticipant).where(
                models.QueueParticipant.queue_id == queue.id,
                models.QueueParticipant.status == "current"
            )
        )
        current_participant = result.scalars().first()
        if current_participant:
            queue.status = "active"
            await db.commit()
            return

        queue.status = "active"

        result = await db.execute(
            select(models.QueueParticipant)
            .where(models.QueueParticipant.queue_id == queue_id)
            .where(models.QueueParticipant.status == "waiting")
            .order_by(models.QueueParticipant.position)
        )
        first = result.scalars().first()
        if first:
            first.status = "current"
            student = await db.get(models.User, first.student_id)
            if student and student.telegram_id:
                await notify_telegram_user(
                    telegram_id=student.telegram_id,
                    message=f"Название очереди: {queue.title}.\nСейчас ваша очередь сдавать. Удачи!",
                    queue_id=queue.id,
                    button="complete"
                )

        await db.commit()


async def maybe_close_queue(db: AsyncSession, queue_id: int):
    result = await db.execute(select(models.Queue).where(models.Queue.id == queue_id))
    queue = result.scalars().first()

    if not queue:
        return

    now = datetime.now(timezone.utc)
    if queue.status == "active" and queue.scheduled_end <= now:
        queue.status = "closed"
        result = await db.execute(
            select(models.QueueParticipant).where(
                models.QueueParticipant.queue_id == queue.id,
                models.QueueParticipant.status == "current"
            )
        )
        current_participant = result.scalars().first()
        if current_participant:
            current_participant.status = "done"
        await db.flush()
        await db.commit()
        return

    # проверка есть ли уже сдающий
    result = await db.execute(
        select(models.QueueParticipant).where(
            models.QueueParticipant.queue_id == queue.id,
            models.QueueParticipant.status == "current"
        )
    )

    current = result.scalars().first()
    if current:
        return

    if queue.status != "active":
        return

    # назначение первого в очереди сдающим
    result = await db.execute(
        select(models.QueueParticipant)
        .where(models.QueueParticipant.queue_id == queue_id)
        .where(models.QueueParticipant.status == "waiting")
        .order_by(models.QueueParticipant.position)
    )
    next_participant = result.scalars().first()
    if next_participant:
        next_participant.status = "current"
        await db.flush()
        await db.commit()


# завершение очереди вручную
async def manual_close_queue(db: AsyncSession, queue_id: int, user_id: int):
    result = await db.execute(
        select(models.Queue).where(models.Queue.id == queue_id)
    )
    queue = result.scalars().first()

    if not queue:
        raise HTTPException(status_code=404, detail="Очередь не найдена")
    if queue.creator_id != user_id:
        raise HTTPException(status_code=403, detail="Вы не владелец очереди")
    if queue.status == "closed":
        raise HTTPException(status_code=400, detail="Очередь уже завершена")

    queue.status = "closed"
    await db.commit()
    return {"detail": "Очередь завершена вручную"}


### ДЛЯ АДМИНИСТРАТОРА ###
async def create_group(db: AsyncSession, name: str):
    existing = await db.execute(select(models.Group).where(models.Group.name == name))
    if existing.scalar():
        raise HTTPException(status_code=400, detail="Группа уже существует")
    group = models.Group(name=name)
    db.add(group)
    await db.commit()
    await db.refresh(group)
    return group


async def create_discipline(db: AsyncSession, name: str):
    existing = await db.execute(select(models.Discipline).where(models.Discipline.name == name))
    if existing.scalar():
        raise HTTPException(status_code=400, detail="Дисциплина уже существует")
    discipline = models.Discipline(name=name)
    db.add(discipline)
    await db.commit()
    await db.refresh(discipline)
    return discipline


async def delete_queue_by_admin(db: AsyncSession, queue_id: int):
    queue = await db.get(models.Queue, queue_id)
    if not queue:
        raise HTTPException(status_code=404, detail="Очередь не найдена")
    await db.execute(delete(models.QueueGroup).where(models.QueueGroup.queue_id == queue.id))
    await db.execute(delete(models.QueueParticipant).where(models.QueueParticipant.queue_id == queue.id))
    await db.delete(queue)
    await db.commit()
    return {"detail": "Очередь удалена администратором"}


async def queue_update_admin(db: AsyncSession, queue_id: int, data: QueueUpdate):
    queue = await db.get(models.Queue, queue_id)
    if not queue:
        raise HTTPException(status_code=404, detail="Очередь не найдена")
    update_data = data.dict(exclude_unset=True)

    for key, value in update_data.items():
        if key != "group_ids":
            setattr(queue, key, value)

    if "group_ids" in update_data:
        await db.execute(delete(models.QueueGroup).where(models.QueueGroup.queue_id == queue.id))
        for group_id in set(update_data["group_ids"]):
            db.add(models.QueueGroup(queue_id=queue_id, group_id=group_id))

    await db.commit()
    result = await db.execute(
        select(models.Queue)
        .options(joinedload(models.Queue.groups), joinedload(models.Queue.discipline))
        .where(models.Queue.id == queue_id)
    )
    queue_with_joins = result.scalars().first()
    return queue_with_joins


async def get_admin_queues(
        db: AsyncSession,
        group_id: Optional[int] = None,
        discipline_id: Optional[int] = None,
        status: Optional[str] = 'active',
        search: Optional[str] = None,
) -> List[models.Queue]:
    now = datetime.now(timezone.utc)

    await db.execute(
        update(models.Queue)
        .where(models.Queue.status == "active")
        .where(models.Queue.scheduled_end <= now)
        .values(status="closed")
    )
    await db.commit()

    base_query = select(models.Queue).options(
        joinedload(models.Queue.groups),
        joinedload(models.Queue.discipline),
        joinedload(models.Queue.creator)
    )
    base_result = await db.execute(base_query)
    all_queues = base_result.unique().scalars().all()

    for queue in all_queues:
        if queue.status == "upcoming":
            await maybe_start_queue(db, queue.id)
        elif queue.status == "active":
            await maybe_close_queue(db, queue.id)

    query = select(models.Queue).options(
        joinedload(models.Queue.groups),
        joinedload(models.Queue.discipline),
        joinedload(models.Queue.creator)
    )

    if status == "active":
        query = query.where(models.Queue.status == "active")
    elif status == "closed":
        query = query.where(models.Queue.status == "closed")
    elif status == "upcoming":
        query = query.where(models.Queue.status == "upcoming")
    elif status == "all":
        pass
    elif status:
        raise HTTPException(status_code=400, detail="Недопустимый статус")

    if group_id:
        query = query.where(models.Queue.group_ids.any(group_id))
    if discipline_id:
        query = query.where(models.Queue.discipline_id == discipline_id)
    if search:
        search_like = f"%{search.lower()}%"
        query = query.join(models.Discipline).join(models.QueueGroup).join(models.Group).where(
            or_(
                func.lower(models.Queue.title).ilike(search_like),
                func.lower(models.Discipline.name).ilike(search_like),
                func.lower(models.Group.name).ilike(search_like),
            )
        )

    result = await db.execute(query)
    return result.unique().scalars().all()
