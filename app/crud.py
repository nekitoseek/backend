# crud-функции
from fastapi import HTTPException
from sqlalchemy import delete, func, update, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from passlib.hash import bcrypt
from datetime import datetime, timezone
from typing import List, Optional
from app import models, schemas

# создание пользователя
async def create_user(db: AsyncSession, user: schemas.UserCreate):
    hashed_password = bcrypt.hash(user.password)
    db_user = models.User(
        username=user.username,
        password_hash=hashed_password,
        full_name=user.full_name,
        email=user.email,
        role=user.role
    )
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)
    return db_user

# создание очереди
async def create_queue(db: AsyncSession, queue: schemas.QueueCreate, teacher_id: int):
    new_queue = models.Queue(
        title=queue.title,
        description=queue.description,
        scheduled_date=queue.scheduled_date,
        created_at=datetime.now(timezone.utc),
        status='active',
        teacher_id=teacher_id,
        discipline_id=queue.discipline_id
    )

    db.add(new_queue)
    await db.flush() # получаем ID новой очереди

    # привязка группы к очереди
    for group_id in set(queue.group_ids):
        # db.add(models.QueueGroup(queue_id=new_queue.id, group_id=group_id))
        existing = await db.execute(
            select(models.QueueGroup)
            .where(models.QueueGroup.queue_id == new_queue.id)
            .where(models.QueueGroup.group_id == group_id)
        )

        if not existing.scalar():
            db.add(models.QueueGroup(queue_id=new_queue.id, group_id=group_id))

    # print("Создание очереди:", queue)
    # print("Привязываем группы:", queue.group_ids)
    # print("Очередь создана с ID:", new_queue.id)
    await db.commit()
    await db.refresh(new_queue)
    return new_queue
    # print("QUEUE DATA:", queue)

# просмотр очередей
async def get_queues(
    db: AsyncSession,
    group_id: Optional[int] = None,
    discipline_id: Optional[int] = None,
    status: Optional[str] = 'active'
) -> List[models.Queue]:
    query = select(models.Queue)

    if status:
        query = query.where(models.Queue.status == status)
    if group_id:
        query = query.where(models.Queue.group_ids.any(group_id))
    if discipline_id:
        query = query.where(models.Queue.discipline_id == discipline_id)

    result = await db.execute(query)
    return result.scalars().all()

# удаление очереди
async def delete_queue(db: AsyncSession, queue_id: int, current_user: models.User):
    result = await db.execute(select(models.Queue).where(models.Queue.id == queue_id))
    queue = result.scalars().first()
    if not queue:
        raise HTTPException(status_code=404, detail="Очередь не найдена")
    if queue.teacher_id != current_user.id:
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
    if queue.teacher_id != current_user.id:
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
        select(models.User)
        .join(models.QueueParticipant, models.QueueParticipant.student_id == models.User.id)
        .where(models.QueueParticipant.queue_id == queue_id)
        .order_by(models.QueueParticipant.position)
    )
    return result.scalars().all()

# запись в очередь
async def join_queue(db: AsyncSession, queue_id: int, student_id: int):
    # проверка есть ли студент уже в очереди
    result = await db.execute(
        select(models.QueueParticipant).where(
            models.QueueParticipant.queue_id == queue_id,
            models.QueueParticipant.student_id == student_id,
            models.QueueParticipant.status == "waiting"
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
    max_position = result.scalar()
    if max_position is None:
        max_position = 0

    new_participant = models.QueueParticipant(
        queue_id=queue_id,
        student_id=student_id,
        position=max_position + 1,
        status="waiting"
    )

    db.add(new_participant)
    await db.commit()
    await db.refresh(new_participant)
    return new_participant

# покидание очереди
async def leave_queue(db: AsyncSession, queue_id: int, student_id: int):
    result = await db.execute(
        select(models.QueueParticipant).where(
            models.QueueParticipant.queue_id == queue_id,
            models.QueueParticipant.student_id == student_id,
            models.QueueParticipant.status == "waiting"
        )
    )
    participant = result.scalars().first()
    if not participant:
        raise HTTPException(status_code=404, detail="Вы не стоите в этой очереди")

    participant.status = "left"
    await send_notification(db, participant.student_id, "Вы покинули очередь")
    await db.commit()
    return {"detail": "Вы покинули очередь"}

# вызов следующего по очереди
async def call_next_student(db: AsyncSession, queue_id: int, teacher_id: int):
    result = await db.execute(
        select(models.Queue).where(models.Queue.id == queue_id, models.Queue.teacher_id == teacher_id)
    )
    queue = result.scalars().first()
    if not queue:
        raise HTTPException(status_code=403, detail="Вы не владелец этой очереди")

    result = await db.execute(
        select(models.QueueParticipant).where(models.QueueParticipant.queue_id == queue_id, models.QueueParticipant.status == "waiting")
        .order_by(models.QueueParticipant.position.asc())
    )
    participant = result.scalars().first()
    if not participant:
        raise HTTPException(status_code=404, detail="Очередь пуста")

    participant.status = "called"
    await db.commit()
    await send_notification(db, participant.student_id, "Вы вызваны в очереди")
    return {"detail": f"Студент {participant.student_id} вызван"}

# закрытие очереди
async def close_queue(db: AsyncSession, queue_id: int, teacher_id: int):
    result = await db.execute(
        select(models.Queue).where(models.Queue.id == queue_id, models.Queue.teacher_id == teacher_id)
    )
    queue = result.scalars().first()
    if not queue:
        raise HTTPException(status_code=403, detail="Вы не владелец этой очереди")

    queue.status = "closed"

    await db.execute(
        update(models.QueueParticipant).where(models.QueueParticipant.queue_id == queue_id, models.QueueParticipant.status == "waiting")
        .values(status="closed")
    )

    result = await db.execute(
        select(models.QueueParticipant).where(models.QueueParticipant.queue_id == queue_id, models.QueueParticipant.status == "closed")
    )
    participants = result.scalars().all()
    for participant in participants:
        await send_notification(db, participant.student_id, "Очередь была закрыта, вы не успели!")

    await db.commit()
    return {"detail": "Очередь успешно закрыта"}

# сдача завершена
async def complete_current_student(db: AsyncSession, queue_id: int, teacher_id: int):
    result = await db.execute(
        select(models.Queue).where(models.Queue.id == queue_id, models.Queue.teacher_id == teacher_id)
    )
    queue = result.scalars().first()
    if not queue:
        raise HTTPException(status_code=403, detail="Вы не владелец этой очереди")

    result = await db.execute(
        select(models.QueueParticipant)
        .where(models.QueueParticipant.queue_id == queue_id, models.QueueParticipant.status == "called")
        .order_by(models.QueueParticipant.position.asc())
    )
    participant = result.scalars().first()
    if not participant:
        raise HTTPException(status_code=404, detail="Нет вызванного студента")
    participant.status = "left"
    await db.commit()
    return {"detail": f"Студент {participant.student_id} завершил сдачу"}

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