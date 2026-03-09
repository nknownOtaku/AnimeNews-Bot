import aiohttp
import asyncio
import logging
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup
import subprocess
import threading
import pymongo
import feedparser
from config import API_ID, API_HASH, BOT_TOKEN, URL_A, START_PIC, MONGO_URI, ADMINS

from webhook import start_webhook
from modules.rss.rss import news_feed_loop

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# MongoDB setup
mongo_client = pymongo.MongoClient(MONGO_URI)
db = mongo_client["AnimeNewsBot"]
user_settings_collection = db["user_settings"]
global_settings_collection = db["global_settings"]
sent_news_collection = db["sent_news"]  # For duplicate prevention

# Pyrogram client
app = Client("AnimeNewsBot", api_id=API_ID, api_hash=API_HASH, bot_token=BOT_TOKEN)

# Start webhook in background thread
webhook_thread = threading.Thread(target=start_webhook, daemon=True)
webhook_thread.start()


def setup_database():
    """Initialize MongoDB collections with capped settings for auto-rotation"""
    try:
        # sent_news: capped collection for duplicate prevention (auto-deletes oldest)
        if "sent_news" not in db.list_collection_names():
            db.create_collection("sent_news", capped=True, size=1048576, max=100)
            db.sent_news.create_index("entry_id", unique=True)
            logger.info("✅ Collection 'sent_news' created (capped @ 100 docs)")
        
        # Optional: logs collection for persistent error tracking
        if "logs" not in db.list_collection_names():
            db.create_collection("logs", capped=True, size=2097152, max=500)
            logger.info("✅ Collection 'logs' created (capped @ 500 docs)")
            
    except Exception as e:
        logger.error(f"❌ Database setup error: {e}", exc_info=True)


async def escape_markdown_v2(text: str) -> str:
    """Escape markdown special characters (Pyrogram v2 compatible)"""
    return text


async def send_message_to_user(chat_id: int, message: str, image_url: str = None):
    """Helper to send message/photo to user"""
    try:
        if image_url:
            await app.send_photo(chat_id, image_url, caption=message)
        else:
            await app.send_message(chat_id, message)
    except Exception as e:
        logger.error(f"Error sending message to {chat_id}: {e}")


@app.on_message(filters.command("start"))
async def start(client, message):
    """Handle /start command"""
    chat_id = message.chat.id
    buttons = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("ᴍᴀɪɴ ʜᴜʙ", url="https://t.me/Bots_Nation"),
            InlineKeyboardButton("ꜱᴜᴩᴩᴏʀᴛ ᴄʜᴀɴɴᴇʟ", url="https://t.me/Bots_Nation_Support"),
        ],
        [
            InlineKeyboardButton("ᴅᴇᴠᴇʟᴏᴩᴇʀ", url="https://t.me/darkxside78"),
        ],
    ])

    await app.send_photo(
        chat_id, 
        START_PIC,
        caption=(
            f"**ʙᴀᴋᴋᴀᴀᴀ {message.from_user.username}!!!**\n"
            f"**ɪ ᴀᴍ ᴀɴ ᴀɴɪᴍᴇ ɴᴇᴡs ʙᴏᴛ.**\n"
            f"**ɪ ᴛᴀᴋᴇ ᴀɴɪᴍᴇ ɴᴇᴡs ᴄᴏᴍɪɴɢ ғʀᴏᴍ ʀss ꜰᴇᴇᴅs ᴀɴᴅ ᴀᴜᴛᴏᴍᴀᴛɪᴄᴀʟʟʏ ᴜᴘʟᴏᴀᴅ ɪᴛ ᴛᴏ ᴍʏ ᴍᴀsᴛᴇʀ's ᴀɴɪᴍᴇ ɴᴇᴡs ᴄʜᴀɴɴᴇʟ.**"
        ),
        reply_markup=buttons
    )
    logger.info(f"👋 /start command used by @{message.from_user.username} ({chat_id})")


@app.on_message(filters.command("news"))
async def connect_news(client, message):
    """Handle /news command to set target channel (admin only)"""
    chat_id = message.chat.id
    
    if message.from_user.id not in ADMINS:
        await app.send_message(chat_id, "❌ You do not have permission to use this command.")
        logger.warning(f"⚠️ Unauthorized /news attempt by @{message.from_user.username} ({chat_id})")
        return
    
    if len(message.text.split()) == 1:
        await app.send_message(chat_id, "❌ Please provide a channel id or username (without @).")
        return

    channel = " ".join(message.text.split()[1:]).strip()
    global_settings_collection.update_one(
        {"_id": "config"}, 
        {"$set": {"news_channel": channel}}, 
        upsert=True
    )
    await app.send_message(chat_id, f"✅ News channel set to: @{channel}")
    logger.info(f"📬 News channel updated to @{channel} by admin @{message.from_user.username}")


@app.on_message(filters.command("status"))
async def bot_status(client, message):
    """Handle /status command to show bot stats (admin only)"""
    if message.from_user.id not in ADMINS:
        return
    
    try:
        total_sent = sent_news_collection.count_documents({})
        config = global_settings_collection.find_one({"_id": "config"})
        channel = config.get("news_channel", "Not set") if config else "Not set"
        
        status_msg = (
            f"📊 **Bot Status**\n\n"
            f"🗄️ Total news sent: `{total_sent}/100`\n"
            f"📬 Target channel: `@{channel}`\n"
            f"⏱ Check interval: `30 minutes`\n"
            f"📡 Feed: `MyAnimeList RSS (hardcoded)`\n"
            f"🔄 Auto-rotate: `Enabled (oldest deleted at 100)`"
        )
        await app.send_message(message.chat.id, status_msg)
        logger.info(f"📊 Status requested by @{message.from_user.username}")
        
    except Exception as e:
        logger.error(f"❌ Status command error: {e}")
        await app.send_message(message.chat.id, "❌ Error fetching status")


@app.on_message(filters.command("clear"))
async def clear_sent_news(client, message):
    """Handle /clear command to reset sent news tracking (admin only)"""
    if message.from_user.id not in ADMINS:
        await app.send_message(message.chat.id, "❌ Admins only")
        return
    
    try:
        deleted = sent_news_collection.delete_many({})
        await app.send_message(
            message.chat.id, 
            f"✅ Cleared `{deleted.deleted_count}` entries from sent_news collection"
        )
        logger.info(f"🗑️ Cleared {deleted.deleted_count} entries by @{message.from_user.username}")
    except Exception as e:
        logger.error(f"❌ Clear command error: {e}")
        await app.send_message(message.chat.id, "❌ Error clearing data")


async def main():
    """Main entry point"""
    logger.info("🔌 Initializing AnimeNewsBot...")
    
    # Setup database collections (capped for auto-rotation)
    setup_database()
    
    # Start Pyrogram client
    await app.start()
    logger.info("✅ Bot connected to Telegram")
    
    # Start the MAL news feed loop (4 args for compatibility, urls ignored internally)
    # Note: rss.py uses hardcoded MAL RSS regardless of URL_A value
    logger.info("🚀 Starting MAL news feed loop (30-min interval, MAL-only)")
    asyncio.create_task(news_feed_loop(app, db, global_settings_collection, [URL_A]))
    
    logger.info("🎉 Bot is running! Press Ctrl+C to stop.")
    
    # Keep the event loop alive
    await asyncio.Event().wait()


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Bot stopped by user (Ctrl+C)")
    except Exception as e:
        logger.error(f"💥 Fatal error: {e}", exc_info=True)
    finally:
        # Cleanup
        mongo_client.close()
        logger.info("🔌 Database connection closed")
