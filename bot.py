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
from google_auth_oauthlib.flow import InstalledAppFlow
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
          creds.refresh(Request())
      else:
          flow = InstalledAppFlow.from_client_secrets_file(
              'credentials.json', SCOPES)
          creds = flow.run_local_server(port=0)
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
    service = build('drive', 'v3', credentials=getCreds(), cache_discovery=False)
    metadata = {'name': filename}
    media = MediaFileUpload(filepath, chunksize=1024 * 1024, mimetype=mime_type, resumable=True)
    request = service.files().create(body=metadata, media_body=media)
    response = None
    while response is None:
        status, response = request.next_chunk()
        if status:
            print("Uploaded %d%%." % int(status.progress() * 100))
    return response


bot = Client(
    "drive_bot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.TOKEN,
    in_memory=True,  # no session file needs to persist across restarts
)


@bot.on_message(filters.command("start"))
async def start(client, message: Message):
    await message.reply_text("Upload files here.")


@bot.on_message(filters.document)
async def file_handler(client, message: Message):
    doc = message.document

    if doc.file_size and doc.file_size > MAX_TELEGRAM_FILE_SIZE:
        size_mb = doc.file_size / (1024 * 1024)
        limit_mb = MAX_TELEGRAM_FILE_SIZE / (1024 * 1024)
        await message.reply_text(
            f"❌ That file is {size_mb:.1f}MB. This bot can only handle files up to {limit_mb:.0f}MB."
        )
        return

    filename = doc.file_name
    try:
        filepath = await client.download_media(message, file_name=filename)
        await asyncio.to_thread(upload_to_drive, filepath, filename, doc.mime_type)
        await message.reply_text("✅ File uploaded!")
    except Exception:
        logger.exception("Upload failed")
        await message.reply_text("❌ Something went wrong uploading that file. Check the logs for details.")
    finally:
        silentremove(filename)


if __name__ == '__main__':
    bot.run()
