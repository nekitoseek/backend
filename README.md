# Стек технологий
FastAPI — фреймворк для разработки API  
SQLAlchemy — асинхронная работа с базой данных  
PostgreSQL — база данных  
Pydantic — валидация данных  
JWT (JSON Web Tokens) — аутентификация  
Passlib — хэширование паролей  
asyncpg — драйвер PostgreSQL  

# Установка и запуск проекта
## Клонировать репозиторий
``` git clone https://github.com/your-username/queue-system.git ```  
``` cd queue-system/backend ```  
## Создать и активировать виртуальное окружение
``` python3 -m venv venv ```  
``` source venv/bin/activate  # для Linux/macOS ```  
``` venv\Scripts\activate     # для Windows ```  

## Установить зависимости
``` pip install -r requirements.txt```  

## Настроить .env
Создать файл .env в папке app/ и добавить туда строку: ``` DATABASE_URL=postgresql+asyncpg://postgres:12345678@localhost:5432/queue_db ```  

## Запустить сервер
``` uvicorn app.main:app --reload ```  

# Документация API:
<http://localhost:8000/docs>

# Структура проекта
``` app/
├── main.py            # Точки входа и маршруты API  
├── auth.py            # Аутентификация пользователей  
├── crud.py            # Логика взаимодействия с БД  
├── models.py          # Модели базы данных (SQLAlchemy)  
├── schemas.py         # Pydantic-схемы запросов и ответов  
├── database.py        # Подключение к базе данных  
├── config.py          # Конфигурация проекта  
└── .env               # Переменные окружения
```

# Функционал
Регистрация студентов и преподавателей  
Авторизация через JWT токен  
Создание, редактирование и удаление очередей  
Присоединение студентов к очереди  
Вызов студентов преподавателем  
Закрытие очереди  
Уведомления студентам
