# Use an older Python version where legacy collections mapping works natively
FROM python:3.8-slim

# Set work directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y gcc libffi-dev && rm -rf /var/lib/apt/lists/*

# Copy requirements and install missing pieces
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt google-auth-oauthlib flask

# Force the config file to directly grab Render's environment variables
RUN echo "import os\nTOKEN = os.environ.get('TOKEN', os.environ.get('TELEGRAM_TOKEN'))\nclass Config:\n    TOKEN = TOKEN" > config.py

# Copy the rest of the code
COPY . .

# Expose the Flask port we added
EXPOSE 8080

# Run the bot
CMD ["python", "bot.py"]
