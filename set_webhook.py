"""
Corre esto UNA sola vez desde tu computadora, despues de tener el bot
desplegado en Render, para decirle a Telegram donde mandar los mensajes.

Uso:
    python set_webhook.py <BOT_TOKEN> <URL_DE_RENDER>

Ejemplo:
    python set_webhook.py 123456:ABC-DEF https://gastobot.onrender.com
"""
import sys
import requests

if len(sys.argv) != 3:
    print("Uso: python set_webhook.py <BOT_TOKEN> <URL_DE_RENDER>")
    sys.exit(1)

token = sys.argv[1]
url = sys.argv[2].rstrip("/")

r = requests.get(f"https://api.telegram.org/bot{token}/setWebhook", params={
    "url": f"{url}/webhook"
})
print(r.json())
