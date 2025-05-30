from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ApplicationBuilder, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes
from telegram.request import HTTPXRequest
from typing import Optional
import httpx

API_BASE_URL = "http://localhost:8000"
BOT_TOKEN = "7929460692:AAFcGZNcyaqr7mTfkTW-Zc8_G2XjLEseHBI"

user_tokens = {}
login_state = {}

async def login(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id

    if tg_id in user_tokens:
        await update.message.reply_text("Вы уже авторизовались. Если хотите войти под другим пользователем – введите команду /start для сброса.")
        return

    await update.message.reply_text("Введите ваш логин:")
    login_state[update.effective_user.id] = {"step": "username"}

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id
    text = update.message.text.strip()

    if tg_id in login_state:
        state = login_state[tg_id]

        if state["step"] == "username":
            state["username"] = text
            state["step"] = "password"
            await update.message.reply_text("Введите пароль:")
        elif state["step"] == "password":
            username = state["username"]
            password = text
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"{API_BASE_URL}/login",
                    data={"username": username, "password": password}
                )
                if response.status_code == 200:
                    tokens = response.json()
                    user_tokens[tg_id] = {
                        "access": tokens["access_token"],
                        "refresh": tokens["refresh_token"],
                    }
                    del login_state[tg_id]

                    await client.patch(
                        f"{API_BASE_URL}/me",
                        json={"telegram_id": str(tg_id)},
                        headers={"Authorization": f"Bearer {tokens['access_token']}"}
                    )

                    await update.message.reply_text("Авторизация успешна!")
                else:
                    await update.message.reply_text("Неверный логин или пароль.")
                    del login_state[tg_id]
        return
    await update.message.reply_text("Напишите /login для авторизации.")

async def get_valid_access_token(tg_id: int) -> Optional[str]:
    tokens = user_tokens.get(tg_id)
    if not tokens:
        return None

    access_token = tokens["access"]
    refresh_token = tokens["refresh"]

    async with httpx.AsyncClient() as client:
        check = await client.get(f"{API_BASE_URL}/me", headers={"Authorization": f"Bearer {access_token}"})
        if check.status_code == 200:
            return access_token

        refresh_resp = await client.post(
            f"{API_BASE_URL}/refresh",
            json={"refresh_token": refresh_token}
        )
        if refresh_resp.status_code == 200:
            new_token = refresh_resp.json()["access_token"]
            user_tokens[tg_id]["access"] = new_token
            return new_token
    return None

async def handle_complete_button(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    tg_id = query.from_user.id

    token = await get_valid_access_token(tg_id)
    if not token:
        await query.edit_message_text("Авторизация истекла. Введите /login заново.")
        return

    queue_id = query.data.replace("complete_", "")
    async with httpx.AsyncClient() as client:
        response = await client.post(f"{API_BASE_URL}/queues/{queue_id}/complete", headers={"Authorization": f"Bearer {token}"})
        if response.status_code == 200:
            await query.edit_message_text("Вы успешно отметились как сдавший!")
        else:
            await query.edit_message_text("Ошибка. Возможно, Вы не сдающий.")

async def handle_start_login_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    tg_id = query.from_user.id
    if tg_id in user_tokens:
        await query.edit_message_text("Вы уже авторизованы.")
        return
    login_state[tg_id] = {"step": "username"}
    await query.edit_message_text("Введите ваш логин:")

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tg_id = update.effective_user.id

    user_tokens.pop(tg_id, None)
    login_state.pop(tg_id, None)

    async with httpx.AsyncClient() as client:
        await client.post(
            f"{API_BASE_URL}/reset-telegram",
            json={"telegram_id": str(tg_id)}
        )

    keyboard = [
        [InlineKeyboardButton("Авторизоваться", callback_data="start_login")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Добро пожаловать! Авторизуйтесь, чтобы продолжить.",
        reply_markup=reply_markup
    )

async def queue_notify(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Подписка на уведомления активирована!")

def main():
    request = HTTPXRequest(connect_timeout=5.0, read_timeout=10.0)

    app = ApplicationBuilder().token(BOT_TOKEN).request(request).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("login", login))
    app.add_handler(CommandHandler("subscribe", queue_notify))
    app.add_handler(CallbackQueryHandler(handle_start_login_callback, pattern="start_login$"))
    app.add_handler(CallbackQueryHandler(handle_complete_button, pattern=r"^complete_\d+$"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    app.run_polling()

if __name__ == "__main__":
    main()