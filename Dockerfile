# Use an older Python version where legacy collections mapping works natively
FROM python:3.8-slim

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y gcc libffi-dev && rm -rf /var/lib/apt/lists/*

# Copy requirements and install missing pieces
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt google-auth-oauthlib flask

# Copy the repository files (ensure token.pickle is NOT in your repo)
COPY . .

# Force the fresh configuration file to map variables directly from Render.
# NOTE: module-level variables, NOT a class -- bot.py reads config.TOKEN directly.
RUN echo "import os\nTOKEN = os.environ.get('TOKEN', os.environ.get('TELEGRAM_TOKEN'))\nG_DRIVE_CLIENT_ID = os.environ.get('G_DRIVE_CLIENT_ID')\nG_DRIVE_CLIENT_SECRET = os.environ.get('G_DRIVE_CLIENT_SECRET')" > config.py

# Expose the Flask port we added
EXPOSE 8080

# On boot, look at Render's secure memory, turn the string back into a file, and start the script
CMD python -c "import os, base64; token_data = os.environ.get('PICKLED_TOKEN'); f = open('token.pickle', 'wb'); f.write(base64.b64decode(token_data)) if token_data else print('Warning: No token found')" && python bot.py
