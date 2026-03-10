FROM python:3.10-slim

WORKDIR /app

# Install system dependencies including Tesseract OCR and languages
RUN apt-get update && apt-get install -y \
    tesseract-ocr \
    tesseract-ocr-fra \
    tesseract-ocr-ara \
    libgl1 \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements from backend folder
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy all project files
COPY backend ./backend
COPY frontend ./frontend
COPY cheques_essai ./cheques_essai

# Set working directory to backend for uvicorn
WORKDIR /app/backend

# Render/Railway assign a dynamic PORT env var
ENV PORT=10000

# Start command using the dynamic port
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
