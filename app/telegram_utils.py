# telegram_utils.py
import httpx

TELEGRAM_BOT_TOKEN = "7929460692:AAFcGZNcyaqr7mTfkTW-Zc8_G2XjLEseHBI"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

async def notify_telegram_user(telegram_id: str, message: str, queue_id: int = None, button: str = "join"):
    print(f"==> Пытаемся отправить сообщение Telegram ID {telegram_id}")
    payload = {
        "chat_id": telegram_id,
        "text": message
    }
    if queue_id is not None:
        if button == "join":
            payload["reply_markup"] = {
                "inline_keyboard": [
                    [{"text": "Записаться", "callback_data": f"join_queue_{queue_id}"}]
                ]
            }
        elif button == "complete":
            payload["reply_markup"] = {
                "inline_keyboard": [
                    [{"text": "Я сдал / Приём завершён", "callback_data": f"complete_{queue_id}"}]
                ]
            }

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            await client.post(f"{TELEGRAM_API_URL}/sendMessage", json=payload)
        except Exception as e:
            print(f"Ошибка при отправке сообщения Telegram ID {telegram_id}: {e}:")


# from telegram import InlineKeyboardButton, InlineKeyboardMarkup
# from bot.main import application
#
# async def notify_telegram_user(telegram_id: str, message: str, queue_id: int = None):
#     if application is None:
#         print("Бот ещё не инициализирован")
#         return
#
#     # Кнопка для записи, если передан queue_id
#     reply_markup = None
#     if queue_id is not None:
#         reply_markup = InlineKeyboardMarkup([
#             [InlineKeyboardButton("Записаться", callback_data=f"join_queue_{queue_id}")]
#         ])
#
#     try:
#         print(f"Отправка сообщения пользователю {telegram_id}")
#         await application.bot.send_message(
#             chat_id=telegram_id,
#             text=message,
#             reply_markup=reply_markup
#         )
#     except Exception as e:
#         print(f"Ошибка при отправке сообщения Telegram ID {telegram_id}: {e}")