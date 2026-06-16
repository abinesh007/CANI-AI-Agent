import sqlite3
import datetime

DB_PATH = "cani.db"

def get_connection():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_connection()
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS conversations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        user_message TEXT,
        bot_response TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS water_intake (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        amount_ml INTEGER,
        note TEXT
    )''')
    c.execute('''CREATE TABLE IF NOT EXISTS meal_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        timestamp TEXT,
        meal_type TEXT CHECK(meal_type IN ('breakfast','lunch','dinner','snack')),
        had_meal INTEGER CHECK(had_meal IN (0,1))
    )''')
    conn.commit()
    conn.close()

def log_conversation(user_msg, bot_response):
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT INTO conversations (timestamp, user_message, bot_response) VALUES (?, ?, ?)",
              (datetime.datetime.now().isoformat(), user_msg, bot_response))
    conn.commit()
    conn.close()

def log_water_intake(amount_ml, note=""):
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT INTO water_intake (timestamp, amount_ml, note) VALUES (?, ?, ?)",
              (datetime.datetime.now().isoformat(), amount_ml, note))
    conn.commit()
    conn.close()

def get_today_water_intake():
    conn = get_connection()
    c = conn.cursor()
    today = datetime.date.today().isoformat()
    c.execute("SELECT SUM(amount_ml) FROM water_intake WHERE date(timestamp) = ?", (today,))
    total = c.fetchone()[0]
    conn.close()
    return total if total is not None else 0

def get_recent_conversations(limit=5):
    conn = get_connection()
    c = conn.cursor()
    c.execute("SELECT user_message, bot_response FROM conversations ORDER BY timestamp DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows

def log_meal(meal_type, had):
    conn = get_connection()
    c = conn.cursor()
    c.execute("INSERT INTO meal_log (timestamp, meal_type, had_meal) VALUES (?, ?, ?)",
              (datetime.datetime.now().isoformat(), meal_type, 1 if had else 0))
    conn.commit()
    conn.close()