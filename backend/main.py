import os
import re
import pytesseract
from PIL import Image
from io import BytesIO

from fastapi import FastAPI, File, UploadFile, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

app = FastAPI(title="ChekScan App - PFE OCR", version="2.0.0")

# Setup templates and static files to point to the frontend directory
# Assuming the default docker setup maps the frontend directory correctly or we copy it
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")

# Make sure frontend dir exists (for local testing without docker)
if not os.path.exists(frontend_dir):
    frontend_dir = "frontend"

app.mount("/static", StaticFiles(directory=frontend_dir), name="static")
templates = Jinja2Templates(directory=frontend_dir)

def extract_cheque_data(text: str) -> dict:
    """Parse OCR text using Regex to find cheque fields."""
    data = {
        "bankName": "Non détectée",
        "amountNum": "Non trouvé",
        "date": "Non trouvée",
        "micr": "Non détectée"
    }
    
    # 1. Banque
    lower_text = text.lower()
    if "attijariwafa" in lower_text or "wafa" in lower_text:
        data["bankName"] = "Attijariwafa Bank"
    elif "cih" in lower_text:
        data["bankName"] = "CIH Bank"
    elif "bmce" in lower_text or "boa" in lower_text:
        data["bankName"] = "BOA / BMCE"
    elif "populaire" in lower_text or "bcp" in lower_text:
        data["bankName"] = "Banque Populaire"

    # 2. Montant
    amount_match = re.search(r'(?:#|dh|mad)?\s*(\d{1,3}(?:[ .,]\d{3})*(?:[.,]\d{2}))\s*(?:#|dh|mad)?', text, re.IGNORECASE)
    if amount_match:
        data["amountNum"] = amount_match.group(1).replace(' ', '').replace(',', '.')

    # 3. Date 
    date_match = re.search(r'\b(\d{2}[/-]\d{2}[/-]\d{4})\b', text)
    if date_match:
        data["date"] = date_match.group(1).replace('-', '/')

    # 4. MICR (Bas du chèque)
    micr_match = re.search(r'([<\d\s]{20,})', text)
    if micr_match:
        data["micr"] = micr_match.group(1).strip()

    return data


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    """Render the homepage with the upload form."""
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/upload", response_class=HTMLResponse)
async def process_check(request: Request, file: UploadFile = File(...)):
    """Process the uploaded file and render the result page."""
    try:
        # 1. Read Image
        contents = await file.read()
        image = Image.open(BytesIO(contents))
        
        # 2. OCR Processing (French + Arabic)
        extracted_text = pytesseract.image_to_string(image, lang='fra+ara')
        
        # 3. Parse Data
        cheque_data = extract_cheque_data(extracted_text)
        
        # 4. Render result page with data
        return templates.TemplateResponse("result.html", {
            "request": request, 
            "data": cheque_data, 
            "raw_text": extracted_text,
            "filename": file.filename
        })
        
    except Exception as e:
        return templates.TemplateResponse("result.html", {
            "request": request, 
            "error": str(e)
        })
