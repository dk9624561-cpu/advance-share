import socket

# Force IPv4 across all socket connections (fixes Hugging Face / Docker IPv6 handshake timeout to Telegram)
_original_getaddrinfo = socket.getaddrinfo

def _ipv4_only_getaddrinfo(host, port, family=0, *args, **kwargs):
    if family in (0, socket.AF_UNSPEC):
        family = socket.AF_INET
    return _original_getaddrinfo(host, port, family, *args, **kwargs)

socket.getaddrinfo = _ipv4_only_getaddrinfo

import os
import logging
import secrets
import html
import asyncio
from telegram.error import RetryAfter, NetworkError
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.request import HTTPXRequest
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
    CallbackQueryHandler,
)

import config
import database

# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

async def safe_send_message(context, chat_id, text, reply_markup=None, parse_mode=None):
    """Sends a message, retrying automatically if rate limited (RetryAfter) or on temporary NetworkErrors."""
    while True:
        try:
            return await context.bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_markup=reply_markup,
                parse_mode=parse_mode
            )
        except RetryAfter as e:
            logger.warning(f"Rate limit hit! Sleeping for {e.retry_after} seconds before retrying...")
            await asyncio.sleep(e.retry_after)
        except NetworkError as e:
            logger.warning(f"Network error: {e}. Retrying in 5 seconds...")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
            raise e

async def safe_copy_message(context, chat_id, from_chat_id, message_id, protect_content=False):
    """Copies a message, retrying automatically if rate limited (RetryAfter) or on temporary NetworkErrors."""
    while True:
        try:
            return await context.bot.copy_message(
                chat_id=chat_id,
                from_chat_id=from_chat_id,
                message_id=message_id,
                protect_content=protect_content
            )
        except RetryAfter as e:
            logger.warning(f"Rate limit hit! Sleeping for {e.retry_after} seconds before retrying...")
            await asyncio.sleep(e.retry_after)
        except NetworkError as e:
            logger.warning(f"Network error: {e}. Retrying in 5 seconds...")
            await asyncio.sleep(5)
        except Exception as e:
            logger.error(f"Failed to copy message: {e}")
            raise e

cached_bot_username = None

async def post_init(application) -> None:
    """Registers commands menu on bot startup."""
    from telegram import BotCommand, BotCommandScopeAllPrivateChats
    commands = [
        BotCommand("start", "🚀 Start the bot or request a file"),
        BotCommand("help", "❓ Show all available commands"),
        BotCommand("add_mapping", "🔗 Link a source channel to destination"),
        BotCommand("remove_mapping", "❌ Remove a channel mapping link"),
        BotCommand("add_user", "👤 Add/renew user membership access"),
        BotCommand("remove_user", "🚫 Revoke/delete user membership"),
        BotCommand("add_admin", "🔑 Grant admin privileges to a user"),
        BotCommand("remove_admin", "🔒 Revoke admin privileges from a user"),
        BotCommand("list_users", "📋 List all active subscribers"),
        BotCommand("reset_user", "🔄 Reset download limit for a specific user"),
        BotCommand("reset_all", "🔄 Reset download limit for ALL users"),
        BotCommand("status", "📊 Check bot mappings and status info")
    ]
    try:
        await application.bot.delete_my_commands()
        await application.bot.set_my_commands(commands)
        await application.bot.set_my_commands(commands, scope=BotCommandScopeAllPrivateChats())
        logger.info("Bot commands refreshed and registered successfully on Telegram.")
    except Exception as e:
        logger.error(f"Failed to set bot commands: {e}")

def get_admin_user_id() -> int:
    """Helper to get admin user ID from settings database, falling back to config."""
    db_val = database.get_setting("admin_user_id")
    if db_val is not None:
        try:
            return int(db_val)
        except ValueError:
            return db_val
    return config.ADMIN_USER_ID

async def get_bot_username(context: ContextTypes.DEFAULT_TYPE) -> str:
    """Helper to get bot username dynamically, with caching."""
    global cached_bot_username
    if cached_bot_username:
        return cached_bot_username
    if config.BOT_USERNAME:
        cached_bot_username = config.BOT_USERNAME
        return cached_bot_username
    try:
        bot_info = await context.bot.get_me()
        cached_bot_username = bot_info.username
        return cached_bot_username
    except Exception as e:
        logger.error(f"Failed to fetch bot username dynamically: {e}")
        return "bot"

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles the /start command, including deep-linked file codes."""
    chat_id = update.effective_chat.id
    user_id = update.effective_user.id
    
    # Check if there are arguments passed with /start (e.g., /start file_code)
    if context.args:
        file_code = context.args[0]
        logger.info(f"User {chat_id} requested lecture with code: {file_code}")
        
        lecture = database.get_lecture(file_code)
        if lecture:
            # Check daily download limit for non-admin users (exempting admins)
            is_admin = database.is_admin(user_id)
            if not is_admin:
                daily_count = database.get_user_daily_download_count(user_id)
                daily_limit = getattr(config, 'DAILY_LIMIT', 5)
                if daily_count >= daily_limit:
                    logger.info(f"User {user_id} blocked: daily limit ({daily_limit}) reached")
                    await update.message.reply_text(
                        f"⚠️ **Daily Limit Reached!**\n\n"
                        f"आप 1 दिन में केवल {daily_limit} लेक्चर्स ही ले सकते हैं। आपका limit रोज़ रात **02:00 AM IST** पर reset होता है।\n"
                        f"You can only request up to {daily_limit} lectures per day. Limit resets daily at **2:00 AM IST**.",
                        parse_mode="Markdown"
                    )
                    return

            try:
                # Copy the original message from Source Channel to the user's private chat
                await safe_copy_message(
                    context=context,
                    chat_id=chat_id,
                    from_chat_id=lecture["source_chat_id"],
                    message_id=lecture["source_message_id"],
                    protect_content=True
                )
                
                # Log this download if the requester is not the admin
                if not is_admin:
                    database.add_download(user_id, file_code)
                    
                logger.info(f"Successfully copied lecture {file_code} to user {chat_id}")
            except Exception as e:
                logger.error(f"Failed to copy message to user {chat_id}: {e}")
                await update.message.reply_text(
                    "❌ Sorry, I couldn't deliver the file. Make sure I am still an administrator in the source channel."
                )
        else:
            await update.message.reply_text(
                "❌ Sorry, this lecture could not be found. It might have been removed or the link is invalid."
            )
    else:
        # Check if Admin ID is configured; if not, claim it for this user!
        admin_id = get_admin_user_id()
        if not admin_id:
            database.set_setting("admin_user_id", str(user_id))
            welcome_text = (
                "👋 **Welcome to the Lecture Delivery Bot!**\n\n"
                "No Administrator was configured, so **you have been automatically registered as the Administrator**! 😎\n\n"
                f"👤 **Your Admin User ID:** `{user_id}`\n"
                "You can now run admin commands like `/add_mapping` and `/status`!"
            )
            await update.message.reply_text(welcome_text, parse_mode="Markdown")
            logger.info(f"Automatically registered user {user_id} as the bot administrator.")
            return

        # Standard welcome message for all users (since downloads are public)
        welcome_text = (
            "👋 **Welcome to the Lecture Delivery Bot!**\n\n"
            "I help deliver files and lectures directly to you privately.\n"
            "To get a lecture, click the **'Get Lecture 📥'** button in the index channel.\n\n"
            f"ℹ️ **Your Telegram User ID:** `{user_id}`\n\n"
            "💡 Type `/help` to see all available commands!"
        )
        await update.message.reply_text(welcome_text, parse_mode="Markdown")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Displays all available bot commands."""
    user_id = update.effective_user.id
    is_admin_user = database.is_admin(user_id)
    
    help_text = "🤖 **Telegram File Share Bot Commands**\n\n"
    
    help_text += "👤 **User Commands:**\n"
    help_text += "• `/start` - Start bot or request lecture\n"
    help_text += "• `/help` - Show all available commands\n\n"
    
    if is_admin_user:
        help_text += "🔑 **Admin Commands:**\n"
        help_text += "• `/add_mapping <source_id> <dest_id>` - Link channel A to B\n"
        help_text += "• `/remove_mapping <source_id>` - Remove channel link\n"
        help_text += "• `/add_user <user_id> <days>` - Add/renew subscriber\n"
        help_text += "• `/remove_user <user_id>` - Remove subscriber\n"
        help_text += "• `/list_users` - List all subscribers\n"
        help_text += "• `/add_admin <user_id>` - Add sub-admin\n"
        help_text += "• `/remove_admin <user_id>` - Remove sub-admin\n"
        help_text += "• `/reset_user <user_id>` - Reset limit for 1 user\n"
        help_text += "• `/reset_all` - Reset limit for ALL users\n"
        help_text += "• `/status` - Check bot status & mappings\n"
        
    await update.message.reply_text(help_text, parse_mode="Markdown")

async def add_mapping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Command to map a Source channel to a Destination channel. Allowed for any authorized user/subscriber and admin."""
    user_id = update.effective_user.id
    if not database.is_user_authorized(user_id):
        await update.message.reply_text("❌ You are not authorized to run this command. You must be added to the bot.")
        return
        
    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ **Usage:** `/add_mapping <source_channel_id> <destination_channel_id>`\n"
            "Example: `/add_mapping -1001234567890 -10009876543210`",
            parse_mode="Markdown"
        )
        return
        
    source_str, dest_str = context.args[0], context.args[1]
    try:
        source_id = int(source_str)
        dest_id = int(dest_str)
    except ValueError:
        await update.message.reply_text("❌ Invalid Channel IDs. They must be numbers starting with `-100`.")
        return
        
    success = database.add_mapping(source_id, dest_id)
    if success:
        await update.message.reply_text(
            f"✅ **Channel Link Added!**\n\n"
            f"📢 **Source A:** `{source_id}`\n"
            f"📖 **Index B:** `{dest_id}`",
            parse_mode="Markdown"
        )
        logger.info(f"Admin {user_id} added mapping: {source_id} -> {dest_id}")
    else:
        await update.message.reply_text("❌ Failed to add mapping to database.")

async def remove_mapping(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to remove a source channel mapping."""
    user_id = update.effective_user.id
    if not database.is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized to run this command.")
        return
        
    if not context.args:
        await update.message.reply_text(
            "⚠️ **Usage:** `/remove_mapping <source_channel_id>`\n"
            "Example: `/remove_mapping -1001234567890`",
            parse_mode="Markdown"
        )
        return
        
    source_str = context.args[0]
    try:
        source_id = int(source_str)
    except ValueError:
        await update.message.reply_text("❌ Invalid Channel ID. It must be a number.")
        return
        
    removed = database.remove_mapping(source_id)
    if removed:
        await update.message.reply_text(f"✅ **Removed link** for Source Channel A: `{source_id}`", parse_mode="Markdown")
        logger.info(f"Admin {user_id} removed mapping for: {source_id}")
    else:
        await update.message.reply_text("❌ Mapping not found or database error.")

async def add_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to add a new admin."""
    user_id = update.effective_user.id
    if not database.is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized to run this command.")
        return
    if not context.args:
        await update.message.reply_text("⚠️ **Usage:** `/add_admin <user_id>`\nExample: `/add_admin 123456789`", parse_mode="Markdown")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID. It must be a number.")
        return
    if database.add_admin(target_id):
        await update.message.reply_text(f"🔑 **Success!** User `{target_id}` is now registered as an administrator.", parse_mode="Markdown")
        logger.info(f"Admin {user_id} added new admin: {target_id}")
    else:
        await update.message.reply_text("❌ Failed to add administrator.")

async def remove_admin(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to remove an admin."""
    user_id = update.effective_user.id
    if not database.is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized to run this command.")
        return
    if not context.args:
        await update.message.reply_text("⚠️ **Usage:** `/remove_admin <user_id>`\nExample: `/remove_admin 123456789`", parse_mode="Markdown")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID. It must be a number.")
        return
        
    # Prevent owner from removing themselves
    if target_id == get_admin_user_id():
        await update.message.reply_text("❌ You cannot remove the primary owner from administrators.")
        return
        
    if database.remove_admin(target_id):
        await update.message.reply_text(f"🔒 **Success!** User `{target_id}` has been removed from administrators.", parse_mode="Markdown")
        logger.info(f"Admin {user_id} removed admin: {target_id}")
    else:
        await update.message.reply_text("❌ Admin not found or database error.")

async def add_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to grant or extend user subscription access."""
    user_id = update.effective_user.id
    if not database.is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized to run this command.")
        return
    if len(context.args) < 2:
        await update.message.reply_text(
            "⚠️ **Usage:** `/add_user <user_id> <days>`\n"
            "Example: `/add_user 123456789 30`",
            parse_mode="Markdown"
        )
        return
    try:
        target_id = int(context.args[0])
        days = int(context.args[1])
    except ValueError:
        await update.message.reply_text("❌ Invalid arguments. Both User ID and Days must be numbers.")
        return
        
    if database.add_user(target_id, days):
        await update.message.reply_text(
            f"👤 **User Authorized!**\n\n"
            f"🆔 **User ID:** `{target_id}`\n"
            f"📅 **Duration:** `{days} days`",
            parse_mode="Markdown"
        )
        logger.info(f"Admin {user_id} added user subscription: {target_id} for {days} days")
    else:
        await update.message.reply_text("❌ Failed to add user subscription.")

async def remove_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to revoke user subscription immediately."""
    user_id = update.effective_user.id
    if not database.is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized to run this command.")
        return
    if not context.args:
        await update.message.reply_text("⚠️ **Usage:** `/remove_user <user_id>`\nExample: `/remove_user 123456789`", parse_mode="Markdown")
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID. It must be a number.")
        return
    if database.remove_user(target_id):
        await update.message.reply_text(f"🚫 **Success!** Revoked access for user `{target_id}`.", parse_mode="Markdown")
        logger.info(f"Admin {user_id} revoked subscription for: {target_id}")
    else:
        await update.message.reply_text("❌ User not found or database error.")

async def list_users(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to list all subscribers."""
    user_id = update.effective_user.id
    if not database.is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized to run this command.")
        return
    users = database.list_users()
    if not users:
        await update.message.reply_text("📋 **No subscribers registered yet.** Use `/add_user` to grant access.", parse_mode="Markdown")
        return
        
    users_str = "📋 **Subscriber List:**\n\n"
    for idx, u in enumerate(users, 1):
        status_emoji = "🟢" if u["is_active"] else "🔴"
        users_str += f"{idx}. {status_emoji} ID: `{u['user_id']}` | Days Left: `{u['days_left']}` | Expires: `{u['expires_at']}`\n"
    await update.message.reply_text(users_str, parse_mode="Markdown")

async def reset_user(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to reset daily download limit for a single specific user."""
    user_id = update.effective_user.id
    if not database.is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized to run this command.")
        return
    if not context.args:
        await update.message.reply_text(
            "⚠️ **Usage:** `/reset_user <user_id>`\n"
            "Example: `/reset_user 123456789`",
            parse_mode="Markdown"
        )
        return
    try:
        target_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("❌ Invalid user ID. It must be a number.")
        return
        
    if database.reset_user_limit(target_id):
        await update.message.reply_text(
            f"🔄 **Success!** Daily download limit for user `{target_id}` has been reset to 0.",
            parse_mode="Markdown"
        )
        logger.info(f"Admin {user_id} reset daily download limit for user {target_id}")
    else:
        await update.message.reply_text("❌ Failed to reset user limit.")

async def reset_all(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to reset daily download limit for ALL users."""
    user_id = update.effective_user.id
    if not database.is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized to run this command.")
        return
        
    if database.reset_all_limits():
        await update.message.reply_text(
            "🔄 **Success!** Daily download limit for **ALL users** has been reset to 0.",
            parse_mode="Markdown"
        )
        logger.info(f"Admin {user_id} reset daily download limit for ALL users")
    else:
        await update.message.reply_text("❌ Failed to reset all user limits.")

async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to check configurations and list all mappings."""
    user_id = update.effective_user.id
    if not database.is_admin(user_id):
        await update.message.reply_text("❌ You are not authorized to run this command.")
        return
        
    # List mappings from database
    mappings = database.list_mappings()
    
    mapping_list_str = ""
    if mappings:
        for idx, m in enumerate(mappings, 1):
            mapping_list_str += f"{idx}. `{m['source_channel_id']}` ➡️ `{m['destination_channel_id']}`\n"
    else:
        mapping_list_str = "*No mappings configured yet. Use /add_mapping to add mappings.*\n"
        
    # Get .env fallbacks
    env_source = config.SOURCE_CHANNEL_ID or "Not configured"
    env_dest = config.DESTINATION_CHANNEL_ID or "Not configured"
    
    # Count admins and active users
    admin_list = database.list_admins()
    admins_count = len(admin_list) + 1 # Include primary admin
    users_list = database.list_users()
    active_users_count = sum(1 for u in users_list if u["is_active"])
    
    status_text = (
        "📊 **Bot Channel Mapping & User Status**\n\n"
        f"👤 **Primary Owner ID:** `{get_admin_user_id()}`\n"
        f"🔑 **Total Admins:** `{admins_count}`\n"
        f"🟢 **Active Subscribers:** `{active_users_count}`\n\n"
        f"🔗 **Active Channel Mappings:**\n"
        f"{mapping_list_str}\n"
        f"🌐 **Fallback .env Configuration:**\n"
        f"📢 Source A: `{env_source}`\n"
        f"📖 Index B: `{env_dest}`\n"
    )
    await update.message.reply_text(status_text, parse_mode="Markdown")

def parse_lecture_info(text: str):
    if not text:
        return "Untitled Lecture/Media", None
        
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    video_title = None
    batch_name = None
    
    for line in lines:
        if "Video Title :" in line:
            video_title = line.split("Video Title :", 1)[1].strip()
        elif "Summary Title :" in line:
            video_title = line.split("Summary Title :", 1)[1].strip()
        elif "Batch Name :" in line:
            batch_name = line.split("Batch Name :", 1)[1].strip()
            
    # Fallback if no specific tags found
    if not video_title:
        if len(lines) > 0:
            first_line = lines[0]
            if ":" not in first_line or ("Video Id :" not in first_line and "Summary Id :" not in first_line):
                video_title = first_line
            else:
                if len(lines) > 1:
                    second_line = lines[1]
                    if ":" in second_line:
                        video_title = second_line.split(":", 1)[1].strip()
                    else:
                        video_title = second_line
                else:
                    video_title = "Untitled Lecture"
        else:
            video_title = "Untitled Lecture/Media"
            
    return video_title, batch_name

async def channel_post_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles messages posted in channels."""
    channel_post = update.channel_post
    if not channel_post:
        return
        
    chat_id = channel_post.chat.id
    message_id = channel_post.message_id
    
    # Check if there is an active mapping for this source channel
    destination_channel = database.get_mapping(chat_id)
    
    # Fallback to .env values
    if not destination_channel:
        if chat_id == config.SOURCE_CHANNEL_ID:
            destination_channel = config.DESTINATION_CHANNEL_ID
            logger.info(f"Using fallback config routing for source channel {chat_id}")
        else:
            logger.info(f"Ignored channel post from untracked channel ID: {chat_id}")
            return
            
    logger.info(f"New post detected in Source Channel (ID: {chat_id}, Message ID: {message_id})")
    
    # Extract plain text for database logs
    raw_text = channel_post.caption or channel_post.text
    video_title, _ = parse_lecture_info(raw_text)
    
    # Extract original HTML formatting (preserving bold, italics, blockquotes/quotes, etc.)
    title_html = channel_post.caption_html or channel_post.text_html
    if not title_html:
        title_html = "Untitled Lecture/Media"
    
    # Generate a unique file code and ensure it doesn't already exist
    while True:
        file_code = secrets.token_hex(4) # 8-character hex code
        if not database.get_lecture(file_code):
            break
            
    # Save the lecture details to the database (saving plain text title for logs)
    success = database.add_lecture(
        file_code=file_code,
        source_chat_id=chat_id,
        source_message_id=message_id,
        title=video_title
    )
    
    if not success:
        logger.error(f"Failed to save lecture info to database for message {message_id}")
        return
        
    # Post the exact original HTML content to Destination Channel B (preserving exact original formatting)
    index_text = title_html
    keyboard = [
        [InlineKeyboardButton("Get Lecture 📥", callback_data=f"get_{file_code}")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await safe_send_message(
            context=context,
            chat_id=destination_channel,
            text=index_text,
            reply_markup=reply_markup,
            parse_mode="HTML"
        )
        logger.info(f"Successfully posted lecture index for {file_code} in Destination Channel {destination_channel}")
    except Exception as e:
        logger.error(f"Failed to post index in Destination Channel (ID: {destination_channel}): {e}")

async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handles callback queries from the 'Get Lecture 📥' inline buttons in the destination channel."""
    query = update.callback_query
    user_id = query.from_user.id
    data = query.data
    
    if data and data.startswith("get_"):
        file_code = data.split("get_", 1)[1]
        logger.info(f"User {user_id} requested lecture via callback code: {file_code}")
        
        bot_username = await get_bot_username(context)
        try:
            # Answer the callback query by directing the user to the bot's private chat with start parameter.
            # This hides the link on hover/long-press but opens the bot on click!
            await query.answer(url=f"https://t.me/{bot_username}?start={file_code}")
            logger.info(f"Successfully redirected user {user_id} to bot chat for file {file_code}")
        except Exception as e:
            logger.error(f"Failed to redirect user {user_id} to bot chat: {e}")
            await query.answer(
                text="❌ Sorry, this lecture could not be found.",
                show_alert=True
            )

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors caused by updates."""
    logger.error(f"Exception while handling an update: {context.error}")

def main() -> None:
    # Ensure thread has a dedicated asyncio event loop
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    # Validate environment variables first
    errors = config.validate_config()
    if errors:
        error_msg = f"[CRITICAL CONFIG ERROR] {', '.join(errors)}"
        logger.critical(error_msg)
        raise ValueError(error_msg)
        
    # Initialize the database
    database.init_db()
    
    # Initialize HTTPXRequest with IPv4 binding and robust timeouts for Hugging Face
    import httpx
    transport = httpx.AsyncHTTPTransport(local_address="0.0.0.0")
    request_kwargs = {
        "connect_timeout": 30.0,
        "read_timeout": 30.0,
        "write_timeout": 30.0,
        "pool_timeout": 30.0,
        "httpx_kwargs": {"transport": transport}
    }
    
    proxy_url = os.environ.get("TELEGRAM_PROXY") or os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")
    if proxy_url:
        logger.info(f"Using proxy for Telegram Bot: {proxy_url}")
        request_kwargs["proxy"] = proxy_url
        request_kwargs.pop("httpx_kwargs", None)
        
    t_request = HTTPXRequest(**request_kwargs)
    
    builder = (
        ApplicationBuilder()
        .token(config.BOT_TOKEN)
        .post_init(post_init)
        .request(t_request)
        .get_updates_request(t_request)
    )
    
    base_url = os.environ.get("TELEGRAM_BASE_URL")
    if base_url and base_url.strip():
        cleaned_url = base_url.strip().rstrip("/")
        if any(placeholder in cleaned_url for placeholder in ["subdomain.workers.dev", "your-proxy", "example.com", "my-telegram-proxy"]):
            logger.warning(f"Ignoring example/placeholder TELEGRAM_BASE_URL: '{base_url}'. Falling back to default Telegram API.")
        else:
            if not cleaned_url.endswith("/bot"):
                cleaned_url = f"{cleaned_url}/bot"
            logger.info(f"Using custom Telegram Base URL: {cleaned_url}")
            builder.base_url(cleaned_url)
        
    application = builder.build()
    
    # Handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("add_mapping", add_mapping))
    application.add_handler(CommandHandler("remove_mapping", remove_mapping))
    application.add_handler(CommandHandler("add_user", add_user))
    application.add_handler(CommandHandler("remove_user", remove_user))
    application.add_handler(CommandHandler("add_admin", add_admin))
    application.add_handler(CommandHandler("remove_admin", remove_admin))
    application.add_handler(CommandHandler("list_users", list_users))
    application.add_handler(CommandHandler("reset_user", reset_user))
    application.add_handler(CommandHandler("reset_all", reset_all))
    application.add_handler(CommandHandler("status", status))
    # Filter for channel updates
    application.add_handler(MessageHandler(filters.ChatType.CHANNEL, channel_post_handler))
    # Handle inline button callback clicks
    application.add_handler(CallbackQueryHandler(handle_callback_query))
    application.add_error_handler(error_handler)
    
    # Network reachability test
    import urllib.request
    try:
        target_test_url = cleaned_url if ('cleaned_url' in locals() and cleaned_url) else "https://api.telegram.org"
        req = urllib.request.Request(target_test_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            logger.info(f"Network connectivity check to {target_test_url} succeeded (HTTP {resp.status}).")
    except Exception as net_err:
        logger.warning(f"Network connectivity check to Telegram ({target_test_url}) failed: {net_err}.")

    # Start the bot
    logger.info("Bot is starting up... Press Ctrl+C to stop.")
    application.run_polling(
        stop_signals=None,
        close_loop=False,
        bootstrap_retries=-1,
        timeout=30,
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES
    )

if __name__ == "__main__":
    main()