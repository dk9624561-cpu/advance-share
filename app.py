import socket

# Force IPv4 across all socket connections (fixes Hugging Face / Docker IPv6 handshake timeout to Telegram)
_original_getaddrinfo = socket.getaddrinfo

def _ipv4_only_getaddrinfo(host, port, family=0, *args, **kwargs):
    if family in (0, socket.AF_UNSPEC):
        family = socket.AF_INET
    return _original_getaddrinfo(host, port, family, *args, **kwargs)

socket.getaddrinfo = _ipv4_only_getaddrinfo

import threading
import time
import os
import logging
import sqlite3
import urllib.request
import gradio as gr
import database
import config
from bot import main as start_bot

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------
# 1. Anti-Sleep / 0 CPU Bypass Thread (Self-Ping Keep Alive)
# ---------------------------------------------------------
def keep_alive_ping():
    """Periodically pings the local/public server to prevent Hugging Face Space from 0 CPU sleeping."""
    time.sleep(15)  # Wait for server startup
    logger.info("Anti-Sleep keep-alive ping thread started.")
    
    space_host = os.environ.get("SPACE_HOST")
    urls_to_ping = ["http://localhost:7860/"]
    if space_host:
        urls_to_ping.append(f"https://{space_host}/")

    while True:
        for url in urls_to_ping:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 KeepAlive"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    logger.info(f"Keep-Alive ping to {url} succeeded (status {resp.status}). 0 CPU bypassed.")
            except Exception as ping_err:
                logger.debug(f"Ping to {url} failed: {ping_err}")
                
        time.sleep(300)  # Ping every 5 minutes

keep_alive_thread = threading.Thread(target=keep_alive_ping, daemon=True)
keep_alive_thread.start()

# ---------------------------------------------------------
# 2. Telegram Bot Background Thread
# ---------------------------------------------------------
def run_bot_thread():
    while True:
        try:
            logger.info("Launching Telegram Bot runner...")
            start_bot()
        except Exception as e:
            logger.error(f"Bot error: {e}. Reconnecting in 5 seconds...", exc_info=True)
            time.sleep(5)

bot_thread = threading.Thread(target=run_bot_thread, daemon=True)
bot_thread.start()

# ---------------------------------------------------------
# 3. Gradio Dashboard UI
# ---------------------------------------------------------
def get_db_stats():
    db_path = config.DATABASE_PATH or "database.db"
    if not os.path.exists(db_path):
        return "⏳ Database starting up..."
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        mappings = conn.execute("SELECT COUNT(*) FROM channel_mappings").fetchone()[0]
        users = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        lectures = conn.execute("SELECT COUNT(*) FROM lectures").fetchone()[0]
        admins = conn.execute("SELECT COUNT(*) FROM admins").fetchone()[0]
        downloads = conn.execute("SELECT COUNT(*) FROM downloads").fetchone()[0]
        
        status_md = f"""
        # 🟢 Telegram Bot Status: RUNNING
        
        ### 📊 System Statistics:
        * 🔗 **Active Channel Mappings:** `{mappings}`
        * 👤 **Total Administrators:** `{admins + 1}` (1 Owner + {admins} Sub-admins)
        * 🟢 **Active Subscribers:** `{users}`
        * 📖 **Total Lectures in Database:** `{lectures}`
        * 📥 **Total Downloads Processed:** `{downloads}`
        
        ⚡ *Bot & Anti-Sleep Keep-Alive active on Hugging Face Cloud!*
        """
        return status_md
    except Exception as e:
        return f"Error reading database: {e}"

def get_status():
    try:
        return get_db_stats()
    except Exception as e:
        return f"Database error: {e}"

demo = gr.Blocks(title="Telegram File Sharing Bot Dashboard")
with demo:
    gr.HTML("<h1 style='text-align: center; color: #4F46E5; margin-bottom: 20px;'>🤖 Telegram File Sharing Bot Dashboard</h1>")
    status_markdown = gr.Markdown(value=get_status)
    refresh_btn = gr.Button("🔄 Refresh Stats", variant="primary")
    refresh_btn.click(get_status, outputs=status_markdown)
    gr.HTML("<hr><p style='text-align: center; color: #6B7280;'>Hosted on Hugging Face Spaces | Anti-Sleep Active ⚡</p>")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    logger.info(f"Launching Gradio interface on port {port}...")
    demo.launch(server_name="0.0.0.0", server_port=port)
