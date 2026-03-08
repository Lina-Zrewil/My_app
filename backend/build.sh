#!/usr/bin/env bash
# Install Tesseract OCR dependencies
apt-get update && apt-get install -y tesseract-ocr tesseract-ocr-fra tesseract-ocr-ara

# Install Python requirements
pip install -r requirements.txt
