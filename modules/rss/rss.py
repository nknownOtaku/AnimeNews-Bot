import asyncio
import feedparser
import logging
from pyrogram import Client

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

async def fetch_and_send_news(app: Client, db, global_settings_collection, urls):
    logging.info("Checking global configuration...")

    config = global_settings_collection.find_one({"_id": "config"})
    if not config or "news_channel" not in config:
        logging.warning("News channel not configured. Skipping fetch.")
        return

    news_channel = "@" + config["news_channel"]
    logging.info(f"News channel set to: {news_channel}")

    for url in urls:
        logging.info(f"Fetching RSS feed: {url}")

        feed = await asyncio.to_thread(feedparser.parse, url)
        entries = list(feed.entries)[::-1]

        logging.info(f"Total entries fetched: {len(entries)}")

        for entry in entries:
            entry_id = entry.get('id', entry.get('link'))

            logging.info(f"Processing entry: {entry.title}")

            if not db.sent_news.find_one({"entry_id": entry_id}):
                logging.info(f"New entry detected: {entry.title}")

                thumbnail_url = entry.media_thumbnail[0]['url'] if 'media_thumbnail' in entry else None
                msg = f"<b>**{entry.title}**</b>\n\n{entry.summary if 'summary' in entry else ''}\n\n<a href='{entry.link}'>Read more</a>"

                try:
                    logging.info("Waiting 15 seconds before sending message...")
                    await asyncio.sleep(15)

                    if thumbnail_url:
                        logging.info("Sending news with thumbnail...")
                        await app.send_photo(chat_id=news_channel, photo=thumbnail_url, caption=msg)
                    else:
                        logging.info("Sending news without thumbnail...")
                        await app.send_message(chat_id=news_channel, text=msg)

                    db.sent_news.insert_one({
                        "entry_id": entry_id,
                        "title": entry.title,
                        "link": entry.link
                    })

                    logging.info(f"Successfully sent news: {entry.title}")

                except Exception as e:
                    logging.error(f"Error sending news message: {e}")

            else:
                logging.info(f"Skipping already sent entry: {entry.title}")

async def news_feed_loop(app: Client, db, global_settings_collection, urls):
    logging.info("Starting RSS news feed loop...")

    while True:
        logging.info("Running news fetch cycle...")
        await fetch_and_send_news(app, db, global_settings_collection, urls)

        logging.info("Sleeping for 10 seconds before next check...")
        await asyncio.sleep(10)
