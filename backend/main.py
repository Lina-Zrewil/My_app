import os
import re
import logging
import pytesseract
from PIL import Image, ImageOps, ImageEnhance
from io import BytesIO

from fastapi import FastAPI, File, UploadFile, Request, Form, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import requests
import json
import uuid
import hashlib

from database import init_db, save_scan_db, get_all_scans, create_user, get_user_by_email, get_user_by_id, delete_scan, delete_all_scans
from labels import LABELS

app = FastAPI(title="ChekScan", version="2.0.0")

# Setup OpenRouter
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Initialize SQLite
init_db()

# Setup logging
LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
if not os.path.exists(LOG_DIR):
    os.makedirs(LOG_DIR)

LOG_FILE = os.path.join(LOG_DIR, "chatbot.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(LOG_FILE, encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger("ChekScan")

SESSIONS = {}

def hash_password(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()

def get_current_user_id(request: Request):
    return SESSIONS.get(request.cookies.get("session_id"))

@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    public_paths = ["/login", "/register", "/health"]
    if request.url.path.startswith("/static/") or request.url.path in public_paths:
        return await call_next(request)
        
    if not get_current_user_id(request):
        return RedirectResponse(url="/login", status_code=303)
        
    return await call_next(request)

@app.get("/health")
async def health():
    return {"status": "alive", "port": os.environ.get("PORT")}

# Setup templates and static files 
base_dir = os.path.dirname(os.path.abspath(__file__))

# Priority list for finding frontend folder
possible_frontend_paths = [
    os.path.join(os.path.dirname(base_dir), "frontend"), # /app/frontend (if base is /app/backend)
    os.path.join(base_dir, "frontend"),                 # /app/frontend (if base is /app)
    "/app/frontend",                                    # Absolute path in Docker
    "frontend"                                          # Relative path
]

frontend_dir = None
for path in possible_frontend_paths:
    if os.path.exists(path):
        frontend_dir = path
        break

if not frontend_dir:
    # Extreme fallback
    frontend_dir = "frontend"

print(f"DEPLOYMENT DEBUG: Found frontend at: {frontend_dir}")
app.mount("/static", StaticFiles(directory=frontend_dir), name="static")
templates = Jinja2Templates(directory=frontend_dir)

# Simple in-memory chat history
CHAT_HISTORY = []

def get_context(request: Request):
    """Utility to get theme, lang, labels and chat history from cookies"""
    lang = request.cookies.get("lang", "fr")
    theme = request.cookies.get("theme", "dark")
    
    if lang not in ["fr", "ar"]:
        lang = "fr"
    if theme not in ["dark", "light"]:
        theme = "dark"
        
    theme_class = "light-mode" if theme == "light" else "dark-mode"
    
    return {
        "lang": lang,
        "theme": theme,
        "theme_class": theme_class,
        "labels": LABELS[lang],
        "chats": CHAT_HISTORY
    }

def extract_cheque_data(text: str) -> dict:
    # 1. Regex Baseline (Fallback)
    data = {
        "bank_name": "Non détectée",
        "amount": "Non trouvé",
        "payee": "Non trouvé",
        "amount_words": "Non trouvé",
        "date": "Non trouvée",
        "place": "Non trouvé",
        "micr": "Non détectée"
    }
    
    lower_text = text.lower()
    if "attijariwafa" in lower_text or "wafa" in lower_text:
        data["bank_name"] = "Attijariwafa Bank"
    elif "cih" in lower_text:
        data["bank_name"] = "CIH Bank"
    elif "bmce" in lower_text or "boa" in lower_text:
        data["bank_name"] = "BOA / BMCE"
    elif "populaire" in lower_text or "bcp" in lower_text:
        data["bank_name"] = "Banque Populaire"
    elif "generale" in lower_text or "sg" in lower_text:
        data["bank_name"] = "Société Générale"

    amount_match = re.search(r'(?:#|dh|mad)?\s*(\d{1,3}(?:[ .,]\d{3})*(?:[.,]\d{2}))\s*(?:#|dh|mad)?', text, re.IGNORECASE)
    if amount_match:
        data["amount"] = amount_match.group(1).replace(' ', '').replace(',', '.')

    date_match = re.search(r'\b(\d{2}[/-]\d{2}[/-]\d{4})\b', text)
    if date_match:
        data["date"] = date_match.group(1).replace('-', '/')

    micr_match = re.search(r'([<\d\s]{20,})', text)
    if micr_match:
        data["micr"] = micr_match.group(1).strip()

    # 2. AI Improvement (Power Up)
    if OPENROUTER_API_KEY:
        try:
            prompt = f"""
            Tu es un expert en lecture de chèques marocains. Analyse ce texte OCR et extrait les données.
            Réponds UNIQUEMENT avec un objet JSON structuré comme ceci:
            {{
              "bank_name": "Nom de la banque",
              "amount": "Le montant en chiffres (ex: 1250.00)",
              "payee": "Le bénéficiaire",
              "amount_words": "Le montant en lettres",
              "place": "Le lieu d'émission",
              "date": "La date au format JJ/MM/AAAA",
              "micr": "Les chiffres magnétiques en bas du chèque"
            }}
            Si une donnée est manquante, mets "Non trouvé".
            
            Texte OCR:
            ---
            {text}
            ---
            """
            
            headers = {
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "X-Title": "ChekScan AI Extraction"
            }
            payload = {
                "model": "openrouter/auto",
                "messages": [{"role": "user", "content": prompt}]
            }
            
            response = requests.post(OPENROUTER_URL, headers=headers, json=payload, timeout=12)
            if response.status_code == 200:
                result = response.json()
                content = result["choices"][0]["message"]["content"].strip()
                
                # Nettoyage si l'IA ajoute du texte ou des balises
                if "{" in content:
                    content = content[content.find("{"):content.rfind("}")+1]
                
                ai_data = json.loads(content)
                logger.info(f"AI_EXTRACTION_SUCCESS: {ai_data}")
                
                # Mapping pour gérer camelCase ET snake_case
                key_map = {
                    "bank_name": ["bank_name", "bankName", "bank"],
                    "amount": ["amount", "amountNum", "montant"],
                    "payee": ["payee", "beneficiary", "beneficiaire"],
                    "amount_words": ["amount_words", "amountWords", "montant_lettres"],
                    "date": ["date"],
                    "place": ["place", "lieu"],
                    "micr": ["micr", "gencode"]
                }
                
                for target_key, possible_keys in key_map.items():
                    for pk in possible_keys:
                        if ai_data.get(pk) and ai_data[pk] not in ["Non trouvé", "Non détectée", ""]:
                            data[target_key] = str(ai_data[pk])
                            break # On a trouvé une valeur pour ce champ
            else:
                logger.error(f"AI_EXTRACTION_FAIL: code={response.status_code} body={response.text}")
                        
        except Exception as e:
            logger.error(f"AI_EXTRACTION_EXCEPTION: {e}")
            
    return data


@app.get("/set-theme")
async def set_theme(request: Request, theme: str):
    referer = request.headers.get("referer") or "/"
    response = RedirectResponse(url=referer, status_code=303)
    response.set_cookie(key="theme", value=theme, httponly=True)
    return response

@app.get("/set-lang")
async def set_lang(request: Request, lang: str):
    referer = request.headers.get("referer") or "/"
    response = RedirectResponse(url=referer, status_code=303)
    response.set_cookie(key="lang", value=lang, httponly=True)
    return response

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    ctx = {"request": request}
    ctx.update(get_context(request))
    return templates.TemplateResponse("login.html", ctx)

@app.post("/login")
async def login_post(request: Request, email: str = Form(...), password: str = Form(...)):
    user = get_user_by_email(email)
    if user and user["password_hash"] == hash_password(password):
        session_id = str(uuid.uuid4())
        SESSIONS[session_id] = user["id"]
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie("session_id", session_id, max_age=7*24*3600)
        return response
    ctx = {"request": request, "error": "Email ou mot de passe incorrect."}
    ctx.update(get_context(request))
    return templates.TemplateResponse("login.html", ctx)

@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request):
    ctx = {"request": request}
    ctx.update(get_context(request))
    return templates.TemplateResponse("register.html", ctx)

@app.post("/register")
async def register_post(request: Request, email: str = Form(...), username: str = Form(...), password: str = Form(...)):
    if create_user(email, username, hash_password(password)):
        return RedirectResponse(url="/login?registered=1", status_code=303)
    ctx = {"request": request, "error": "Cet email est déjà utilisé."}
    ctx.update(get_context(request))
    return templates.TemplateResponse("register.html", ctx)

@app.get("/logout")
async def logout(request: Request):
    session_id = request.cookies.get("session_id")
    if session_id in SESSIONS:
        del SESSIONS[session_id]
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("session_id")
    return response


@app.post("/chat")
async def chat(request: Request, message: str = Form(...)):
    referer = request.headers.get("referer") or "/"
    CHAT_HISTORY.append({"role": "user", "text": message})
    
    bot_reply = "Clé OPENROUTER_API_KEY non configurée dans l'environnement."
    if OPENROUTER_API_KEY:
        try:
            # Use openrouter/auto which routes to the best available free model
            models_to_try = [
                "openrouter/auto",
                "openrouter/free",
                "meta-llama/llama-3.2-3b-instruct:free"
            ]
            
            headers = {
                "Authorization": f"Bearer {OPENROUTER_API_KEY}",
                "Content-Type": "application/json",
                "HTTP-Referer": "https://chekscan-app.onrender.com", # Optional, for OpenRouter rankings
                "X-Title": "ChekScan Masterpiece"
            }
            
            api_messages = [
                {"role": "system", "content": "Tu es un assistant bancaire expert pour l'application ChekScan. Règle absolue : Tu dois STRICTEMENT répondre dans la langue exacte de l'utilisateur (Français, Arabe classique, ou Darija marocaine). Garde le contexte de la conversation."}
            ]
            
            # Map our internal CHAT_HISTORY format to OpenRouter's required format
            for chat in CHAT_HISTORY:
                role = "assistant" if chat["role"] == "bot" else "user"
                api_messages.append({"role": role, "content": chat["text"]})
                
            for model_id in models_to_try:
                data = {
                    "model": model_id,
                    "messages": api_messages
                }
                
                logger.info(f"CHAT_TRY: model={model_id}, history_length={len(api_messages)}")
                response = requests.post(OPENROUTER_URL, headers=headers, json=data, timeout=20)
                
                if response.status_code == 200:
                    result = response.json()
                    if "choices" in result and len(result["choices"]) > 0:
                        bot_reply = result["choices"][0]["message"]["content"].strip()
                        logger.info(f"CHAT_SUCCESS: model={model_id}")
                        break # Success!
                    else:
                        logger.warning(f"CHAT_EMPTY: model={model_id}, result={result}")
                else:
                    logger.error(f"CHAT_FAIL: model={model_id}, status={response.status_code}, body={response.text}")
                    # Continue to next model
            
            if bot_reply.startswith("Clé OPENROUTER"): # still at default
                 bot_reply = "Désolé, les serveurs d'IA sont temporairement indisponibles. Veuillez réessayer dans quelques instants."
                    
        except Exception as e:
            bot_reply = f"Erreur de connexion IA: {e}"
            logger.exception("CHAT_EXCEPTION")
            
    CHAT_HISTORY.append({"role": "bot", "text": bot_reply})
    redirect_url = referer.split('#')[0] + "#chat-bottom"
    return RedirectResponse(url=redirect_url, status_code=303)

@app.get("/clear_chat")
async def clear_chat(request: Request):
    referer = request.headers.get("referer") or "/"
    CHAT_HISTORY.clear()
    redirect_url = referer.split('#')[0]
    return RedirectResponse(url=redirect_url, status_code=303)


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    ctx = {"request": request}
    ctx.update(get_context(request))
    return templates.TemplateResponse("index.html", ctx)


@app.post("/upload", response_class=HTMLResponse)
async def process_check(request: Request, file: UploadFile = File(...)):
    ctx = {"request": request}
    ctx.update(get_context(request))
    try:
        contents = await file.read()
        image = Image.open(BytesIO(contents))
        
        # --- IMAGE PREPROCESSING FOR BETTER OCR ---
        # 1. Upscale if too small (Targeting ~2000px for better OCR)
        width, height = image.size
        if width < 1500 and height < 1500:
            scale = 2000 / max(width, height)
            new_size = (int(width * scale), int(height * scale))
            image = image.resize(new_size, Image.Resampling.LANCZOS)
            logger.info(f"IMAGE_RESIZED: {width}x{height} -> {new_size[0]}x{new_size[1]}")

        # 2. Convert to grayscale
        gray_image = ImageOps.grayscale(image)
        
        # 3. Enhance Contrast and Sharpness
        contrast = ImageEnhance.Contrast(gray_image).enhance(2.0)
        sharp = ImageEnhance.Sharpness(contrast).enhance(2.0)
        
        # 4. Binarization (Black & White thresholding)
        # Helps Tesseract isolate text from background noise/patterns
        final_image = sharp.point(lambda p: 255 if p > 140 else 0)
        
        extracted_text = pytesseract.image_to_string(final_image, lang='fra+ara')
        cheque_data = extract_cheque_data(extracted_text)
        
        ctx.update({
            "data": cheque_data, 
            "raw_text": extracted_text,
            "filename": file.filename
        })
        return templates.TemplateResponse("result.html", ctx)
        
    except Exception as e:
        ctx.update({"error": str(e)})
        return templates.TemplateResponse("result.html", ctx)


@app.post("/save_scan")
async def save_scan(
    request: Request,
    filename: str = Form(...),
    bank_name: str = Form(...),
    amount: str = Form(...),
    date: str = Form(...),
    micr: str = Form(...),
    payee: str = Form(""),
    amount_words: str = Form(""),
    place: str = Form("")
):
    uid = get_current_user_id(request)
    save_scan_db(uid, filename, bank_name, amount, date, micr, payee, amount_words, place)
    return RedirectResponse(url="/history", status_code=303)


import csv
from io import StringIO

@app.get("/export_csv")
async def export_csv(request: Request):
    uid = get_current_user_id(request)
    scans = get_all_scans(uid)
    output = StringIO()
    writer = csv.writer(output, delimiter=';')
    
    writer.writerow(["ID", "Fichier", "Banque", "Montant", "Date", "MICR", "Beneficiaire", "Montant_Lettres", "Lieu"])
    
    for scan in scans:
        writer.writerow([
            scan.get("id", ""), scan.get("filename", ""), scan.get("bank_name", ""),
            scan.get("amount", ""), scan.get("date", ""), scan.get("micr", ""),
            scan.get("payee", ""), scan.get("amount_words", ""), scan.get("place", "")
        ])    
    
    output.seek(0)
    csv_content = "\ufeff" + output.getvalue()
    return Response(content=csv_content, media_type="text/csv", headers={"Content-Disposition": "attachment; filename=chekscan_export.csv"})

@app.get("/history", response_class=HTMLResponse)
async def history(request: Request):
    ctx = {"request": request}
    ctx.update(get_context(request))
    uid = get_current_user_id(request)
    scans = get_all_scans(uid)
    
    bank_counts = {}
    total_amount = 0.0
    for scan in scans:
        b_name = scan.get("bank_name", "Inconnue")
        if b_name.strip() == "": b_name = "Inconnue"
        bank_counts[b_name] = bank_counts.get(b_name, 0) + 1
        
        amt_str = str(scan.get("amount", "0")).replace(' ', '').replace(',', '.')
        try:
            total_amount += float(amt_str)
        except ValueError:
            pass

    stats = {
        "labels": list(bank_counts.keys()),
        "data": list(bank_counts.values())
    }
    
    total_disp = f"{total_amount:,.2f}".replace(',', ' ')
    ctx.update({"scans": scans, "stats": json.dumps(stats), "total_amount_display": total_disp})
    return templates.TemplateResponse("history.html", ctx)

@app.post("/delete_scan/{scan_id}")
async def delete_scan_route(request: Request, scan_id: int):
    uid = get_current_user_id(request)
    delete_scan(uid, scan_id)
    return RedirectResponse(url="/history", status_code=303)

@app.post("/delete_all")
async def delete_all_scans_route(request: Request):
    uid = get_current_user_id(request)
    delete_all_scans(uid)
    return RedirectResponse(url="/history", status_code=303)
