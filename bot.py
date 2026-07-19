#!/usr/bin/env python
import os
import pickle
import asyncio
import logging
import threading

import config

from pyrogram import Client, filters
from pyrogram.types import Message

from googleapiclient.http import MediaFileUpload
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

from flask import Flask

# Bots that connect via MTProto (this library) can handle files up to 2000MB
# -- Telegram's real per-file limit -- unlike the public HTTP Bot API's 20MB
# download cap. No local Bot API server needed, so this all runs in one
# container/service.
MAX_TELEGRAM_FILE_SIZE = 2000 * 1024 * 1024

# --- tiny Flask app just so Render sees an open HTTP port for health checks ---
flask_app = Flask('')

@flask_app.route('/')
def home(): return "Bot is running"

def run_flask(): flask_app.run(host='0.0.0.0', port=8080)

threading.Thread(target=run_flask, daemon=True).start()

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)


def getCreds():
  # The file token.pickle stores the user's access and refresh tokens, and is
  # created automatically when the authorization flow completes for the first
  # time.
  creds = None
  SCOPES = 'https://www.googleapis.com/auth/drive'
  if os.path.exists('token.pickle'):
      with open('token.pickle', 'rb') as token:
          creds = pickle.load(token)
  if not creds or not creds.valid:
      if creds and creds.expired and creds.refresh_token:
          logger.info("Access token expired -- refreshing...")
          creds.refresh(Request())
          logger.info("Token refreshed successfully.")
      else:
          # No usable refresh token, and this is a headless server -- an
          # interactive flow.run_local_server() call here would just hang
          # forever waiting for a browser that will never show up. Fail
          # loudly instead so it shows up in the logs immediately.
          raise RuntimeError(
              "Google Drive credentials are missing or unrefreshable "
              "(no refresh_token available). Re-run the local auth script "
              "to generate a fresh token.pickle with a refresh token, then "
              "update the PICKLED_TOKEN env var."
          )
      with open('token.pickle', 'wb') as token:
          pickle.dump(creds, token)
  return creds


def silentremove(filename):
    try:
        os.remove(filename)
    except OSError:
        pass


def upload_to_drive(filepath, filename, mime_type):
    """Blocking Drive upload. Called via asyncio.to_thread so it doesn't
    block Pyrogram's event loop while a large file uploads."""
    logger.info("Getting Drive credentials for %s...", filename)
    service = build('drive', 'v3', credentials=getCreds(), cache_discovery=False)
    logger.info("Starting Drive upload for %s...", filename)
    metadata = {'name': filename}
    media = MediaFileUpload(filepath, chunksize=1024 * 1024, mimetype=mime_type, resumable=True)
    request = service.files().create(body=metadata, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            logger.info("Uploaded %d%% of %s", int(status.progress() * 100), filename)
    logger.info("Drive upload complete for %s", filename)
    return response


bot = Client(
    "drive_bot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.TOKEN,
    in_memory=True,  # no session file needs to persist across restarts
)


# Catch every common attachment type -- forwarded files often keep their
# original type (video, audio, etc.) rather than arriving as a generic
# "document", so filters.document alone misses most forwards.
MEDIA_FILTER = (
    filters.document
    | filters.video
    | filters.audio
    | filters.animation
    | filters.voice
    | filters.video_note
)


def extract_media(message: Message):
    """Return (media_object, filename, mime_type) for whichever media type
    is present on the message."""
    for attr, default_ext in (
        ("document", ""), ("video", ".mp4"), ("audio", ".mp3"),
        ("animation", ".gif"), ("voice", ".ogg"), ("video_note", ".mp4"),
    ):
        media = getattr(message, attr, None)
        if media:
            filename = getattr(media, "file_name", None) or f"{media.file_unique_id}{default_ext}"
            mime_type = getattr(media, "mime_type", None)
            return media, filename, mime_type
    return None, None, None


def make_progress_logger(filename):
    last_logged = {"pct": -10}

    def progress(current, total):
        pct = int(current / total * 100) if total else 0
        if pct >= last_logged["pct"] + 10:
            last_logged["pct"] = pct
            logger.info("Downloading %s: %d%% (%.1f/%.1fMB)", filename, pct,
                        current / (1024 * 1024), total / (1024 * 1024))

    return progress


@bot.on_message(filters.command("start"))
async def start(client, message: Message):
    await message.reply_text("Upload files here.")


@bot.on_message(MEDIA_FILTER)
async def file_handler(client, message: Message):
    media, filename, mime_type = extract_media(message)
    if media is None:
        return

    if media.file_size and media.file_size > MAX_TELEGRAM_FILE_SIZE:
        size_mb = media.file_size / (1024 * 1024)
        limit_mb = MAX_TELEGRAM_FILE_SIZE / (1024 * 1024)
        await message.reply_text(
            f"❌ That file is {size_mb:.1f}MB. This bot can only handle files up to {limit_mb:.0f}MB."
        )
        return

    try:
        logger.info("Starting Telegram download for %s (%.1fMB)...", filename, (media.file_size or 0) / (1024 * 1024))
        filepath = await client.download_media(message, file_name=filename, progress=make_progress_logger(filename))
        logger.info("Telegram download complete for %s. Handing off to Drive upload...", filename)
        await asyncio.to_thread(upload_to_drive, filepath, filename, mime_type)
        await message.reply_text("✅ File uploaded!")
    except Exception:
        logger.exception("Upload failed for %s", filename)
        await message.reply_text("❌ Something went wrong uploading that file. Check the logs for details.")
    finally:
        silentremove(filename)


if __name__ == '__main__':
    bot.run()
