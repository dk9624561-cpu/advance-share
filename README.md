# 🤖 Telegram Lecture Saver & Indexing Bot

A Telegram bot designed to automatically index lectures/files from a source channel into a destination index channel with interactive buttons and deliver content directly and securely to users with per-day limits.

## 🚀 Features
- **Auto Indexing**: Automatically listens to channel posts and publishes indexed cards with `Get Lecture 📥` buttons.
- **Protected Content**: Sends files with content protection to prevent forwarding.
- **Daily Download Limits**: Configurable daily limits resetting at 2:00 AM IST.
- **Web Dashboard**: Gradio-based monitoring UI with system stats and anti-sleep keepalive.
- **Admin Commands**: `/add_mapping`, `/remove_mapping`, `/add_user`, `/add_admin`, `/reset_user`, `/status`, etc.

## 🛠️ Deploy on Render

1. Create a new **Web Service** on [Render](https://render.com).
2. Connect your GitHub repository (`lecture-saver-bot`).
3. Set the following settings:
   - **Environment**: `Python 3`
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python app.py`
4. Add **Environment Variables**:
   - `BOT_TOKEN`: Your Telegram Bot token from @BotFather
   - `BOT_USERNAME`: Your bot's username (without `@`)
   - `DAILY_LIMIT`: `5` (optional)
   - `DATABASE_PATH`: `database.db`
5. Click **Deploy Web Service**!
