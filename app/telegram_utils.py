import httpx

TELEGRAM_BOT_TOKEN = "7929460692:AAFcGZNcyaqr7mTfkTW-Zc8_G2XjLEseHBI"
TELEGRAM_API_URL = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

async def notify_telegram_user(telegram_id: str, message: str):
    print(f"==> Пытаемся отправить сообщение Telegram ID {telegram_id}")
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            await client.post(
                f"{TELEGRAM_API_URL}/sendMessage",
                json={"chat_id": telegram_id, "text": message}
            )
        except Exception as e:
            print(f"Ошибка при отправке сообщения Telegram ID {telegram_id}: {e}:")