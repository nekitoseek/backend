import httpx
from typing import Optional
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler,
    ContextTypes, filters
)
from telegram.request import HTTPXRequest


class TelegramBot:
    def __init__(self, token: str, api_base_url: str):
        self.token = token
        self.api_base_url = api_base_url
        self.user_tokens = {}
        self.login_state = {}
        self.application = None
        self.last_queues = {}
        self.last_mode = {}

    def init_app(self):
        request = HTTPXRequest(connect_timeout=15.0, read_timeout=30.0)
        self.application = ApplicationBuilder().token(self.token).request(request).build()

        self.application.add_handler(CommandHandler("start", self.start))
        self.application.add_handler(CommandHandler("login", self.login))
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))
        self.application.add_handler(CallbackQueryHandler(self.handle_login_callback, pattern="start_login$"))
        self.application.add_handler(CallbackQueryHandler(self.handle_join_queue, pattern="^join_queue_"))
        self.application.add_handler(CallbackQueryHandler(self.handle_leave_queue, pattern="^leave_queue_"))
        self.application.add_handler(CallbackQueryHandler(self.handle_complete_button, pattern="^complete_"))

    def run(self):
        self.application.run_polling(close_loop=False)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        tg_id = update.effective_user.id
        self.user_tokens.pop(tg_id, None)
        self.login_state.pop(tg_id, None)

        async with httpx.AsyncClient() as client:
            await client.post(f"{self.api_base_url}/reset-telegram", json={"telegram_id": str(tg_id)})

        keyboard = [[InlineKeyboardButton("Авторизоваться", callback_data="start_login")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Добро пожаловать! Авторизуйтесь, чтобы продолжить.", reply_markup=reply_markup)

    async def login(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        tg_id = update.effective_user.id
        if tg_id in self.user_tokens:
            await update.message.reply_text("Вы уже авторизованы.")
            return
        await update.message.reply_text("Введите ваш логин:")
        self.login_state[tg_id] = {"step": "username"}

    async def handle_login_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        tg_id = query.from_user.id
        if tg_id in self.user_tokens:
            await query.edit_message_text("Вы уже авторизованы.")
            return
        self.login_state[tg_id] = {"step": "username"}
        await query.edit_message_text("Введите ваш логин:")

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        tg_id = update.effective_user.id
        text = update.message.text.strip()

        # Авторизация
        if tg_id in self.login_state:
            state = self.login_state[tg_id]

            if state["step"] == "username":
                state["username"] = text
                state["step"] = "password"
                await update.message.reply_text("Введите пароль:")
                return

            elif state["step"] == "password":
                username = state["username"]
                password = text
                async with httpx.AsyncClient() as client:
                    response = await client.post(
                        f"{self.api_base_url}/login",
                        data={"username": username, "password": password}
                    )
                    if response.status_code == 200:
                        tokens = response.json()
                        self.user_tokens[tg_id] = {
                            "access": tokens["access_token"],
                            "refresh": tokens["refresh_token"],
                        }
                        del self.login_state[tg_id]

                        await client.patch(
                            f"{self.api_base_url}/me",
                            json={"telegram_id": str(tg_id)},
                            headers={"Authorization": f"Bearer {tokens['access_token']}"}
                        )

                        await update.message.reply_text(
                            "Авторизация успешна!",
                            reply_markup=ReplyKeyboardMarkup(
                                [["Мои очереди", "Мои записи"]],
                                resize_keyboard=True
                            )
                        )
                    else:
                        await update.message.reply_text("Неверный логин или пароль.")
                        del self.login_state[tg_id]
                return

        # Обработка после авторизации
        if text == "Мои очереди":
            await self.show_my_queues(update, context)
            return

        if text == "Мои записи":
            await self.show_my_participated_queues(update, context)
            return

        if text.isdigit() and tg_id in self.last_queues and tg_id in self.last_mode:
            idx = int(text) - 1
            queues = self.last_queues[tg_id]
            mode = self.last_mode[tg_id]
            if 0 <= idx < len(queues):
                q = queues[idx]
                if mode == "join":
                    keyboard = InlineKeyboardMarkup([
                        [InlineKeyboardButton("Записаться", callback_data=f"join_queue_{q['id']}")]
                    ])
                elif mode == "leave":
                    keyboard = InlineKeyboardMarkup([
                        [InlineKeyboardButton("Покинуть очередь", callback_data=f"leave_queue_{q['id']}")]
                    ])
                else:
                    keyboard = None

                start = q['scheduled_date'][:16].replace("T", " ")
                end = q['scheduled_end'][:16].replace("T", " ")
                group_names = ", ".join(g['name'] for g in q.get('groups', []))
                discipline = q['discipline']['name'] if q.get('discipline') else "—"

                text_message = (
                    f"*Название:* {q['title']}\n"
                    f"*Дисциплина:* {discipline}\n"
                    f"*Время:* {start} – {end}\n"
                    f"*Группы:* {group_names}"
                )

                await update.message.reply_text(
                    text_message,
                    reply_markup=keyboard,
                    parse_mode="Markdown"
                )
            else:
                await update.message.reply_text("Неверный номер очереди.")
            return

        await update.message.reply_text("Неизвестная команда. Напишите /login или нажмите кнопку.")

    async def get_valid_token(self, tg_id: int) -> Optional[str]:
        tokens = self.user_tokens.get(tg_id)
        if not tokens:
            return None

        access = tokens["access"]
        refresh = tokens["refresh"]

        async with httpx.AsyncClient() as client:
            r = await client.get(f"{self.api_base_url}/me", headers={"Authorization": f"Bearer {access}"})
            if r.status_code == 200:
                return access

            rr = await client.post(f"{self.api_base_url}/refresh", json={"refresh_token": refresh})
            if rr.status_code == 200:
                new_access = rr.json()["access_token"]
                self.user_tokens[tg_id]["access"] = new_access
                return new_access
        return None

    async def show_my_queues(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        tg_id = update.effective_user.id
        self.last_mode[tg_id] = "join"
        token = await self.get_valid_token(tg_id)
        if not token:
            await update.message.reply_text("Авторизация истекла. Введите /login.")
            return

        async with httpx.AsyncClient() as client:
            res = await client.get(f"{self.api_base_url}/queues", headers={"Authorization": f"Bearer {token}"})

        if res.status_code != 200:
            await update.message.reply_text("Не удалось получить очереди.")
            return

        queues = res.json()
        if not queues:
            await update.message.reply_text("Нет доступных очередей.")
            return

        self.last_queues[tg_id] = queues  # сохраняем список для дальнейшего выбора

        message = ""
        for i, q in enumerate(queues, 1):
            group_names = ", ".join(g['name'] for g in q.get('groups', []))
            discipline = q['discipline']['name'] if q.get('discipline') else "—"
            start = q['scheduled_date'][:16].replace("T", " ")
            end = q['scheduled_end'][:16].replace("T", " ")

            message += (
                f"{i}.\n"
                f"*Название:* {q['title']}\n"
                f"*Дисциплина:* {discipline}\n"
                f"*Время:* {start} – {end}\n"
                f"*Группы:* {group_names}\n\n"
            )
        message += "Ответьте номером очереди, чтобы записаться."

        await update.message.reply_text(
            message,
            reply_markup=ReplyKeyboardMarkup([["Мои очереди", "Мои записи"]], resize_keyboard=True),
            parse_mode="Markdown"
        )

    async def show_my_participated_queues(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        tg_id = update.effective_user.id
        self.last_mode[tg_id] = "leave"
        token = await self.get_valid_token(tg_id)
        if not token:
            await update.message.reply_text("Авторизация истекла. Введите /login.")
            return

        async with httpx.AsyncClient() as client:
            res = await client.get(f"{self.api_base_url}/queues", headers={"Authorization": f"Bearer {token}"})
            if res.status_code != 200:
                await update.message.reply_text("Не удалось получить очереди.")
                return

            all_queues = res.json()

            # получить ID пользователя
            res_me = await client.get(f"{self.api_base_url}/me", headers={"Authorization": f"Bearer {token}"})
            user_id = res_me.json()["id"]

            participated = []
            for q in all_queues:
                queue_id = q["id"]
                res_students = await client.get(
                    f"{self.api_base_url}/queues/{queue_id}/students",
                    headers={"Authorization": f"Bearer {token}"}
                )
                students = res_students.json()
                for pos, s in enumerate([s for s in students if s["status"] != "done"], start=1):
                    if s["id"] == user_id:
                        participated.append({
                            "queue": q,
                            "position": pos
                        })
                        break

            if not participated:
                await update.message.reply_text("Вы не участвуете ни в одной активной или будущей очереди.")
                return

            self.last_queues[tg_id] = [p["queue"] for p in participated]

            msg = "*Ваши записи:*\n\n"
            for i, p in enumerate(participated, 1):
                q = p["queue"]
                start = q['scheduled_date'][:16].replace("T", " ")
                end = q['scheduled_end'][:16].replace("T", " ")
                group_names = ", ".join(g['name'] for g in q.get('groups', []))
                discipline = q['discipline']['name'] if q.get('discipline') else "—"
                msg += (
                    f"{i}.\n"
                    f"*Название:* {q['title']}\n"
                    f"*Дисциплина:* {discipline}\n"
                    f"*Время:* {start} – {end}\n"
                    f"*Группы:* {group_names}\n"
                    f"*Ваша позиция:* {p['position']}\n\n"
                )

            await update.message.reply_text(
                msg + "Ответьте номером очереди, чтобы покинуть её.",
                reply_markup=ReplyKeyboardMarkup([["Мои очереди", "Мои записи"]], resize_keyboard=True),
                parse_mode="Markdown"
            )

    async def handle_join_queue(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        tg_id = query.from_user.id
        token = await self.get_valid_token(tg_id)
        if not token:
            await query.edit_message_text("Авторизация истекла. Введите /login.")
            return

        queue_id = query.data.replace("join_queue_", "")
        async with httpx.AsyncClient() as client:
            # записываемся
            r = await client.post(f"{self.api_base_url}/queues/{queue_id}/join",
                                  headers={"Authorization": f"Bearer {token}"})
            if r.status_code == 200:
                # получаем ID текущего пользователя
                res_me = await client.get(f"{self.api_base_url}/me", headers={"Authorization": f"Bearer {token}"})
                user_id = res_me.json()["id"]

                # получаем список участников очереди
                res_students = await client.get(
                    f"{self.api_base_url}/queues/{queue_id}/students",
                    headers={"Authorization": f"Bearer {token}"}
                )
                students = res_students.json()
                active_students = [s for s in students if s["status"] != "done"]

                for pos, s in enumerate(active_students, 1):
                    if s["id"] == user_id:
                        await query.edit_message_text(
                            f"✅ Вы записались.\nТекущая позиция: {pos}"
                        )
                        return

                await query.edit_message_text("✅ Вы записались, но позиция не определена.")
            elif r.status_code == 400:
                await query.edit_message_text("⚠️ Уже записаны или невозможно записаться.")
            else:
                await query.edit_message_text("❌ Ошибка записи в очередь.")

    async def handle_leave_queue(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        tg_id = query.from_user.id
        token = await self.get_valid_token(tg_id)
        if not token:
            await query.edit_message_text("Авторизация истекла. Введите /login.")
            return

        queue_id = query.data.replace("leave_queue_", "")
        async with httpx.AsyncClient() as client:
            r = await client.post(f"{self.api_base_url}/queues/{queue_id}/leave",
                                  headers={"Authorization": f"Bearer {token}"})
        if r.status_code == 200:
            await query.edit_message_text("❎ Вы покинули очередь.")
        else:
            await query.edit_message_text("❌ Не удалось покинуть очередь.")

    async def handle_complete_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        tg_id = query.from_user.id
        token = await self.get_valid_token(tg_id)
        if not token:
            await query.edit_message_text("Авторизация истекла. Введите /login.")
            return
        queue_id = query.data.replace("complete_", "")
        async with httpx.AsyncClient() as client:
            r = await client.post(f"{self.api_base_url}/queues/{queue_id}/complete",
                                  headers={"Authorization": f"Bearer {token}"})
        if r.status_code == 200:
            await query.edit_message_text("Вы завершили сдачу.")
        else:
            await query.edit_message_text("Ошибка. Возможно, вы не в статусе 'сдаёт'.")


# Запуск
if __name__ == "__main__":
    bot = TelegramBot(
        token="7929460692:AAFcGZNcyaqr7mTfkTW-Zc8_G2XjLEseHBI",
        api_base_url="http://localhost:8000"
    )
    bot.init_app()
    bot.run()