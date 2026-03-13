import sqlite3
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

DB_PATH = os.path.join(DATA_DIR, "chekscan.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT,
            bank_name TEXT,
            amount TEXT,
            date TEXT,
            micr TEXT,
            payee TEXT,
            amount_words TEXT,
            place TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    # Migrations (Add columns if they don't exist)
    try:
        cursor.execute("ALTER TABLE scans ADD COLUMN payee TEXT")
        cursor.execute("ALTER TABLE scans ADD COLUMN amount_words TEXT")
        cursor.execute("ALTER TABLE scans ADD COLUMN place TEXT")
    except sqlite3.OperationalError:
        # Columns probably already exist
        pass
        
    conn.commit()
    conn.close()

def save_scan_db(filename, bank_name, amount, date, micr, payee="", amount_words="", place=""):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO scans (filename, bank_name, amount, date, micr, payee, amount_words, place)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (filename, bank_name, amount, date, micr, payee, amount_words, place))
    conn.commit()
    conn.close()

def get_all_scans():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute('SELECT * FROM scans ORDER BY created_at DESC')
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]
