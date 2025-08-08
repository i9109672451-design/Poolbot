# Deploy on Railway

1) Create a new **Empty project** on https://railway.app
2) Open the project -> **Code** -> **Upload** and upload *all files from this ZIP*.
3) Go to **Variables** and add:
   - BOT_TOKEN=... (your Telegram bot token)
   - ADMIN_CHAT_ID=1020534049
4) Go to **Settings** -> **Deployments** and set **Start Command** to:
   python bot.py
5) Press **Deploy**. Your bot will start running.

Note: This ZIP intentionally does NOT contain `.env` for security.
