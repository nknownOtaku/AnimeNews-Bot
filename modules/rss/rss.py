import asyncio
import logging
import feedparser
import re
from datetime import datetime
from pyrogram import Client
from pyrogram.errors import RPCError

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# 🔒 Hardcoded constants - IGNORES passed urls parameter
MAL_RSS_URL = "https://myanimelist.net/rss/news.xml"
CHECK_INTERVAL = 1800  # 30 minutes in seconds
CAPTION_MAX_LENGTH = 1024  # Telegram caption limit


async def fetch_and_send_news(app: Client, db, global_settings_collection, urls=None):
    """
    Fetch MAL RSS and send news with media + caption.
    
    Note: 'urls' parameter is accepted for compatibility but IGNORED.
    This function only uses the hardcoded MyAnimeList RSS feed.
    """
    
    timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    logger.info(f"[{timestamp}] 🔄 Starting MAL news fetch cycle")
    logger.info(f"[{timestamp}] ℹ️  URLs parameter ignored - using hardcoded MAL feed only")
    
    # Load config
    try:
        config = global_settings_collection.find_one({"_id": "config"})
        if not config or "news_channel" not in config:
            logger.warning(f"[{timestamp}] ⚠️ News channel not configured - skipping")
            return
        news_channel = config["news_channel"]
        logger.info(f"[{timestamp}] 📬 Target channel: {news_channel}")
    except Exception as e:
        logger.error(f"[{timestamp}] ❌ Config error: {e}", exc_info=True)
        return

    stats = {"sent": 0, "skipped": 0, "errors": 0}
    
    # Fetch MAL RSS ONLY (ignores any passed URLs)
    try:
        logger.info(f"[{timestamp}] 📡 Fetching: {MAL_RSS_URL}")
        feed = await asyncio.to_thread(feedparser.parse, MAL_RSS_URL)
        entries = list(feed.entries)[:10]  # First 10 items only
        entries.reverse()  # Oldest → newest for chronological sending
        logger.info(f"[{timestamp}] ✅ Parsed {len(entries)} entries from MAL")
    except Exception as e:
        logger.error(f"[{timestamp}] ❌ RSS fetch error: {e}", exc_info=True)
        return

    for idx, entry in enumerate(entries, 1):
        entry_log = f"[{timestamp}] 📰 [{idx}/{len(entries)}]"
        entry_id = entry.get('id', entry.get('link', 'unknown'))
        title = entry.get('title', 'Untitled')[:80]
        
        logger.info(f"{entry_log} Processing: {title}...")
        
        # ── Duplicate check ──
        try:
            if db.sent_news.find_one({"entry_id": entry_id}):
                logger.debug(f"{entry_log} ⏭️ Already sent - skipping")
                stats["skipped"] += 1
                continue
            logger.info(f"{entry_log} ✓ New entry detected")
        except Exception as e:
            logger.error(f"{entry_log} ❌ DB check error: {e}", exc_info=True)
            stats["errors"] += 1
            continue
        
        # ── Extract media (image or video) ──
        media_url = None
        media_type = None
        
        try:
            # Check for media:thumbnail (images)
            if hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
                media_url = entry.media_thumbnail[0].get('url', '').strip()
                media_type = 'photo'
                logger.debug(f"{entry_log} 🖼️ Image found: {media_url[:70]}...")
            
            # Check for media:content (could be video)
            elif hasattr(entry, 'media_content') and entry.media_content:
                for media in entry.media_content:
                    if media.get('medium') == 'video' or media.get('type', '').startswith('video/'):
                        media_url = media.get('url', '').strip()
                        media_type = 'video'
                        logger.debug(f"{entry_log} 🎬 Video found: {media_url[:70]}...")
                        break
                # Fallback to thumbnail if no video found
                if not media_url and hasattr(entry, 'media_thumbnail') and entry.media_thumbnail:
                    media_url = entry.media_thumbnail[0].get('url', '').strip()
                    media_type = 'photo'
        except Exception as e:
            logger.warning(f"{entry_log} ⚠️ Media extraction warning: {e}")
        
        # ── Prepare caption (NO LINKS per requirements) ──
        try:
            # Clean description: remove HTML tags & entities
            raw_desc = entry.get('summary', entry.get('description', ''))
            clean_desc = re.sub(r'<[^>]+>', '', raw_desc)  # Remove HTML tags
            clean_desc = clean_desc.replace('&#039;', "'").replace('&quot;', '"')
            clean_desc = clean_desc.replace('&amp;', '&').replace('&mdash;', '—')
            clean_desc = ' '.join(clean_desc.split())  # Normalize whitespace
            
            # Format publication date
            pub_date = entry.get('published', '')
            if pub_date:
                try:
                    parsed_date = datetime.strptime(pub_date, "%a, %d %b %Y %H:%M:%S %z")
                    pub_date = parsed_date.strftime("%b %d, %Y at %I:%M %p")
                except:
                    pass  # Keep original if parse fails
            
            # Build caption: Title + Description + Date (NO links!)
            caption = f"{entry.title}\n\n"
            remaining = CAPTION_MAX_LENGTH - len(caption) - len(pub_date) - 10
            if len(clean_desc) > remaining:
                clean_desc = clean_desc[:remaining-3] + "..."
            caption += f"{clean_desc}"
            
            logger.debug(f"{entry_log} 📝 Caption ready ({len(caption)}/{CAPTION_MAX_LENGTH} chars)")
            
        except Exception as e:
            logger.error(f"{entry_log} ❌ Caption prep error: {e}", exc_info=True)
            stats["errors"] += 1
            continue
        
        # ── Send to Telegram with media ──
        try:
            logger.info(f"{entry_log} 🚀 Sending with {media_type or 'text'}...")
            await asyncio.sleep(2)  # Small delay to avoid rate limits
            
            if media_url and media_url.startswith('http'):
                if media_type == 'video':
                    await app.send_video(
                        chat_id=news_channel,
                        video=media_url,
                        caption=caption
                        # ❌ REMOVED: timeout=60 (not supported)
                    )
                    logger.info(f"{entry_log} ✅ Sent VIDEO")
                else:  # photo or fallback
                    await app.send_photo(
                        chat_id=news_channel,
                        photo=media_url,
                        caption=caption
                        # ❌ REMOVED: timeout=30 (not supported)
                    )
                    logger.info(f"{entry_log} ✅ Sent PHOTO")
            else:
                # Fallback: text-only message
                await app.send_message(
                    chat_id=news_channel,
                    text=caption
                )
                logger.info(f"{entry_log} ✅ Sent TEXT (no media available)")
                
        except RPCError as e:
            logger.error(f"{entry_log} ❌ Telegram RPC error: {e}", exc_info=True)
            stats["errors"] += 1
            continue
        except Exception as e:
            logger.error(f"{entry_log} ❌ Send error: {e}", exc_info=True)
            stats["errors"] += 1
            continue
        
        # ── Save to DB (duplicate prevention) ──
        try:
            db.sent_news.insert_one({
                "entry_id": entry_id,
                "title": entry.title,
                "media_type": media_type,
                "sent_at": datetime.utcnow()
            })
            logger.info(f"{entry_log} 💾 Saved to DB")
            stats["sent"] += 1
        except Exception as e:
            logger.error(f"{entry_log} ⚠️ DB save warning: {e} (message was sent anyway)")
            stats["sent"] += 1  # Count as sent even if DB fails
    
    # ── Cycle summary ──
    logger.info(
        f"[{timestamp}] 🏁 Cycle complete: "
        f"✅ {stats['sent']} sent | "
        f"⏭️ {stats['skipped']} skipped | "
        f"❌ {stats['errors']} errors"
    )


async def news_feed_loop(app: Client, db, global_settings_collection, urls=None):
    """
    Main loop: MAL RSS only, checks every 30 minutes.
    
    Note: 'urls' parameter is accepted for compatibility but IGNORED.
    """
    
    logger.info("🚀 MAL News Bot STARTED")
    logger.info(f"⏱ Check interval: {CHECK_INTERVAL//60} minutes")
    logger.info(f"📡 Feed: {MAL_RSS_URL} (hardcoded - urls param ignored)")
    logger.info(f"🗄 DB: sent_news collection (duplicate prevention)")
    
    cycle_count = 0
    
    while True:
        cycle_count += 1
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        
        try:
            logger.info(f"\n[{timestamp}] 🔄 Cycle #{cycle_count} beginning...")
            cycle_start = datetime.utcnow()
            
            # Call with 4 args for compatibility (4th arg ignored internally)
            await fetch_and_send_news(app, db, global_settings_collection, urls)
            
            cycle_duration = (datetime.utcnow() - cycle_start).total_seconds()
            next_check = datetime.utcnow().timestamp() + CHECK_INTERVAL
            next_check_str = datetime.fromtimestamp(next_check).strftime("%H:%M:%S")
            
            logger.info(
                f"[{timestamp}] ⏱ Cycle #{cycle_count} done in {cycle_duration:.1f}s | "
                f"Next check at ~{next_check_str}\n"
            )
            
        except KeyboardInterrupt:
            logger.warning("⚠️ Interrupted by user - shutting down")
            break
        except Exception as e:
            logger.error(f"❌ Critical loop error: {e}", exc_info=True)
            logger.info("🔁 Retrying in 60 seconds...")
            await asyncio.sleep(60)
            continue
        
        await asyncio.sleep(CHECK_INTERVAL)
