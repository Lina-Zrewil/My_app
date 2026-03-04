import os
import re
import time
import pytesseract
from PIL import Image
from io import BytesIO
from fastapi import FastAPI, File, UploadFile, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles

app = FastAPI(title="ChekScan API - No JS OCR", version="1.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

@app.get("/health")
def health_check():
    return {"status": "ok", "message": "ChekScan OCR API is running!"}

@app.get("/")
def read_root(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

def extract_cheque_data(text: str) -> dict:
    """
    Parse OCR text using Regex to find cheque fields.
    This is a basic heuristic approach for demonstration.
    """
    data = {
        "bankName": "",
        "bankCode": "",
        "branchCode": "",
        "accountNum": "",
        "checkNum": "",
        "date": "",
        "amountNum": "",
        "amountWords": "",
        "beneficiary": "",
        "micr": ""
    }
    
    # 1. Bank Name detection (Simple keywords)
    lower_text = text.lower()
    if "attijariwafa" in lower_text or "wafa" in lower_text:
        data["bankName"] = "Attijariwafa Bank"
        data["bankCode"] = "047"
    elif "cih" in lower_text:
        data["bankName"] = "CIH Bank"
        data["bankCode"] = "230"
    elif "bmce" in lower_text or "boa" in lower_text:
        data["bankName"] = "BOA / BMCE"
        data["bankCode"] = "011"
    elif "populaire" in lower_text or "bcp" in lower_text:
        data["bankName"] = "Banque Populaire"
        data["bankCode"] = "190"

    # 2. Amount in Numbers
    amount_match = re.search(r'(?:#|dh|mad)?\s*(\d{1,3}(?:[ .,]\d{3})*(?:[.,]\d{2}))\s*(?:#|dh|mad)?', text, re.IGNORECASE)
    if amount_match:
        clean_amount = amount_match.group(1).replace(' ', '').replace(',', '.')
        try:
            data["amountNum"] = float(clean_amount)
        except ValueError:
            data["amountNum"] = amount_match.group(1)

    # 3. Date 
    date_match = re.search(r'\b(\d{2}[/-]\d{2}[/-]\d{4})\b', text)
    if date_match:
        d = date_match.group(1).replace('/', '-')
        parts = d.split('-')
        if len(parts) == 3 and len(parts[2]) == 4:
            data["date"] = f"{parts[2]}-{parts[1]}-{parts[0]}"
        else:
            data["date"] = d

    # 4. MICR Line (Bottom of the check)
    micr_match = re.search(r'([<\d\s]{20,})', text)
    if micr_match:
        micr = micr_match.group(1).strip()
        data["micr"] = micr
        
        clean_micr = micr.replace(' ', '')
        parts = [p for p in clean_micr.split('<') if p]
        
        if len(parts) >= 3:
            if len(parts[0]) >= 8:
                if not data["bankCode"]: data["bankCode"] = parts[0][:3]
                data["branchCode"] = parts[0][3:8]
            if len(parts[1]) >= 11:
                data["accountNum"] = parts[1][:11]
            if len(parts[-1]) >= 7:
                data["checkNum"] = parts[-1][:7]

    if not data["amountWords"]:
        data["amountWords"] = "Non détecté (Nécessite NLP)"
    
    if not data["beneficiary"]:
        data["beneficiary"] = "Non détecté"

    return data


@app.post("/upload")
async def process_check(request: Request, file: UploadFile = File(...)):
    """
    Real OCR Endpoint processing natively via Jinja2 Form.
    """
    try:
        if not file.filename:
            return templates.TemplateResponse("index.html", {"request": request, "error": "Aucun fichier fourni."})

        # 1. Read Image
        contents = await file.read()
        image = Image.open(BytesIO(contents))
        
        # 2. OCR Processing (French + Arabic)
        extracted_text = pytesseract.image_to_string(image, lang='fra+ara')
        
        # 3. Parse Data
        cheque_data = extract_cheque_data(extracted_text)
        
        # Fake confidence score
        found_fields = sum(1 for v in cheque_data.values() if v and "Non détecté" not in str(v))
        confidence = min(100, max(10, found_fields * 15))

        # 4. Return the HTML Result directly
        return templates.TemplateResponse("result.html", {
            "request": request,
            "filename": file.filename,
            "data": cheque_data,
            "confidence": confidence,
            "raw_text": extracted_text
        })
        
    except Exception as e:
        print(f"OCR Error: {e}")
        return templates.TemplateResponse("index.html", {"request": request, "error": str(e)})

# Note: Fake Chat endpoints have been removed as JS is no longer used for Chat
