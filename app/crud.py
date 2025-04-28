# crud-функция
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import joinedload
from sqlalchemy import delete, func
from app.models import User, Queue, QueueGroup, QueueParticipant
from app import schemas
from app.schemas import UserCreate
from passlib.hash import bcrypt
from datetime import datetime, timezone
from typing import List, Optional
from fastapi import HTTPException

# создание пользователя
async def create_user(db: AsyncSession, user: UserCreate):
    hashed_password = bcrypt.hash(user.password)
    db_user = User(
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
    new_queue = Queue(
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
        # db.add(QueueGroup(queue_id=new_queue.id, group_id=group_id))
        existing = await db.execute(
            select(QueueGroup)
            .where(QueueGroup.queue_id == new_queue.id)
            .where(QueueGroup.group_id == group_id)
        )

        if not existing.scalar():
            db.add(QueueGroup(queue_id=new_queue.id, group_id=group_id))

    print("Создание очереди:", queue)
    print("Привязываем группы:", queue.group_ids)
    print("Очередь создана с ID:", new_queue.id)
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
) -> List[Queue]:
    query = select(Queue)

    if status:
        query = query.where(Queue.status == status)
    if group_id:
        query = query.where(Queue.group_ids.any(group_id))
    if discipline_id:
        query = query.where(Queue.discipline_id == discipline_id)

    result = await db.execute(query)
    return result.scalars().all()



# удаление очереди
async def delete_queue(db: AsyncSession, queue_id: int, current_user: User):
    result = await db.execute(select(Queue).where(Queue.id == queue_id))
    queue = result.scalars().first()
    if not queue:
        raise HTTPException(status_code=404, detail="Очередь не найдена")
    if queue.teacher_id != current_user.id:
        raise HTTPException(status_code=403, detail="Нет прав на удаление этой очереди")
    await db.execute(delete(QueueGroup).where(QueueGroup.queue_id == queue_id))
    await db.delete(queue)
    await db.commit()
    return {"detail": "Очередь удалена"}


# редактирование очереди
async def queue_update(
        db: AsyncSession,
        queue_id: int,
        queue_data: schemas.QueueUpdate,
        current_user: User
):
    queue = await db.get(Queue, queue_id)
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
            delete(QueueGroup).where(QueueGroup.queue_id == queue_id)
        )
        for group_id in set(update_data["group_ids"]):
            db.add(QueueGroup(queue_id=queue_id, group_id=group_id))

    await db.commit()
    await db.refresh(queue)
    return queue


# просмотр студентов в очереди
async def get_students_in_queue(db: AsyncSession, queue_id: int):
    result = await db.execute(
        select(User)
        .join(QueueParticipant, QueueParticipant.student_id == User.id)
        .where(QueueParticipant.queue_id == queue_id)
    )
    return result.scalars().all()


# запись в очередь
async def join_queue(db: AsyncSession, queue_id: int, student_id: int):
    # проверка есть ли студент уже в очереди
    result = await db.execute(
        select(QueueParticipant).where(
            QueueParticipant.queue_id == queue_id,
            QueueParticipant.student_id == student_id,
            QueueParticipant.status == "waiting"
        )
    )
    existing = result.scalars().first()
    if existing:
        raise HTTPException(status_code=400, detail="Студент уже в очереди")

    # вычисление позиции в очереди
    result = await db.execute(
        select(func.max(QueueParticipant.position)).where(
            QueueParticipant.queue_id == queue_id,
        )
    )
    max_position = result.scalar()
    if max_position is None:
        max_position = 0

    new_participant = QueueParticipant(
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
        select(QueueParticipant).where(
            QueueParticipant.queue_id == queue_id,
            QueueParticipant.student_id == student_id,
            QueueParticipant.status == "waiting"
        )
    )
    participant = result.scalars().first()
    if not participant:
        raise HTTPException(status_code=404, detail="Вы не стоите в этой очереди")

    participant.status = "left"
    await db.commit()
    return {"detail": "Вы покинули очередь"}


# вызов следующего по очереди
async def call_next_student(db: AsyncSession, queue_id: int, teacher_id: int):
    result = await db.execute(
        select(Queue).where(Queue.queue_id == queue_id, Queue.teacher_id == teacher_id)
    )
    if not queue:
        raise HTTPException(status_code=403, detail="Вы не владелец этой очереди")

    result = await db.execute(
        select(QueueParticipant).where(QueueParticipant.queue_id == queue_id, QueueParticipant.status == "waiting")
        .order_by(QueueParticipant.position.asc())
    )
    participant = result.scalars().first()
    if not participant:
        raise HTTPException(status_code=404, detail="Очередь пуста")

    participant.status = "called"
    await db.commit()
    return {"detail": f"Студент {participant.student_id} вызван"}


# закрытие очереди
async def close_queue(db: AsyncSession, queue_id: int, teacher_id: int):
    result = await db.execute(
        select(Queue).where(Queue.id == queue_id, Queue.teacher_id == teacher_id)
    )
    queue = result.scalars().first()
    if not queue:
        raise HTTPException(status_code=403, detail="Вы не владелец этой очереди")

    queue.status = "closed"

    await db.execute(
        update(QueueParticipant).where(QueueParticipant.queue_id == queue_id, QueueParticipant.status == "waiting")
        .values(status="closed")
    )

    await db.commit()
    return {"detail": "Очередь успешно закрыта"}