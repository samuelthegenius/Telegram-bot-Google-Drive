# Newer Python needed for asyncio.to_thread (3.9+) and current Pyrogram/Kurigram
FROM python:3.11-slim

# Set work directory
WORKDIR /app

# Install system dependencies (gcc/libffi needed to build TgCrypto)
RUN apt-get update && apt-get install -y gcc libffi-dev && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the repository files (ensure token.pickle is NOT in your repo)
COPY . .

# Force the fresh configuration file to map variables directly from Render.
# NOTE: module-level variables, NOT a class -- bot.py reads config.TOKEN etc. directly.
RUN echo "import os\nTOKEN = os.environ.get('TOKEN', os.environ.get('TELEGRAM_TOKEN'))\nAPI_ID = int(os.environ.get('TELEGRAM_API_ID', 0))\nAPI_HASH = os.environ.get('TELEGRAM_API_HASH')\nG_DRIVE_CLIENT_ID = os.environ.get('G_DRIVE_CLIENT_ID')\nG_DRIVE_CLIENT_SECRET = os.environ.get('G_DRIVE_CLIENT_SECRET')" > config.py

# Expose the Flask port we added
EXPOSE 8080

# On boot, look at Render's secure memory, turn the string back into a file, and start the script
CMD python -c "import os, base64; token_data = os.environ.get('PICKLED_TOKEN'); f = open('token.pickle', 'wb'); f.write(base64.b64decode(token_data)) if token_data else print('Warning: No token found')" && python bot.py
