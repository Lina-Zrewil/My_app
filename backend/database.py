import sqlite3
import os

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
if not os.path.exists(DATA_DIR):
    os.makedirs(DATA_DIR)

DB_PATH = os.path.join(DATA_DIR, "chekscan.db")

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    # Create Users Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT UNIQUE NOT NULL,
            username TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    # Create Scans Table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            filename TEXT,
            bank_name TEXT,
            amount TEXT,
            date TEXT,
            micr TEXT,
            payee TEXT,
            amount_words TEXT,
            place TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users (id)
        )
    ''')
    
    # Migrations
    try: cursor.execute("ALTER TABLE scans ADD COLUMN payee TEXT")
    except sqlite3.OperationalError: pass
    
    try: cursor.execute("ALTER TABLE scans ADD COLUMN amount_words TEXT")
    except sqlite3.OperationalError: pass
    
    try: cursor.execute("ALTER TABLE scans ADD COLUMN place TEXT")
    except sqlite3.OperationalError: pass
    
    try: cursor.execute("ALTER TABLE scans ADD COLUMN user_id INTEGER")
    except sqlite3.OperationalError: pass
        
    conn.commit()
    conn.close()

def create_user(email, username, password_hash):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO users (email, username, password_hash) VALUES (?, ?, ?)", (email, username, password_hash))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def get_user_by_email(email):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE email=?", (email,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def get_user_by_id(user_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE id=?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return dict(row) if row else None

def save_scan_db(user_id, filename, bank_name, amount, date, micr, payee="", amount_words="", place=""):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute('''
        INSERT INTO scans (user_id, filename, bank_name, amount, date, micr, payee, amount_words, place)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (user_id, filename, bank_name, amount, date, micr, payee, amount_words, place))
    conn.commit()
    conn.close()

def get_all_scans(user_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    # Support backward compatibility by checking user_id IS NULL or user_id = ?
    cursor.execute('SELECT * FROM scans WHERE user_id=? OR user_id IS NULL ORDER BY created_at DESC', (user_id,))
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

def delete_scan(user_id, scan_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM scans WHERE id=? AND (user_id=? OR user_id IS NULL)", (scan_id, user_id))
    conn.commit()
    conn.close()

def delete_all_scans(user_id):
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM scans WHERE user_id=? OR user_id IS NULL", (user_id,))
    conn.commit()
    conn.close()
