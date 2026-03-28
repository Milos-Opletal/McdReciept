import base64
import cv2
import numpy as np
import sqlite3
import datetime
from datetime import timedelta
from flask import Flask, render_template, request, jsonify
from qreader import QReader

app = Flask(__name__)
reader = QReader(model_size='n')

DB_NAME = "db/scans.sqlite"
TARGET_PREFIX = "https://mcdonalds.fast-insight.com/voc/cz/cs?CODE="


def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS scans
                      (
                          id                    INTEGER PRIMARY KEY AUTOINCREMENT,
                          code                  TEXT,
                          scanned_time          TIMESTAMP,
                          is_valid              BOOLEAN,
                          processed_time        TIMESTAMP,
                          processing_successful BOOLEAN,
                          error                 TEXT
                      )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS messages
                      (
                          id          INTEGER PRIMARY KEY AUTOINCREMENT,
                          text        TEXT NOT NULL,
                          is_reusable BOOLEAN DEFAULT 0,
                          times_used  INTEGER DEFAULT 0,
                          enabled     BOOLEAN DEFAULT 1
                      )''')

    # Updated Settings Table with ALL Configs
    cursor.execute('''
                   CREATE TABLE IF NOT EXISTS settings
                   (
                       id                        INTEGER PRIMARY KEY,
                       percent_message           INTEGER DEFAULT 50,
                       percent_special           INTEGER DEFAULT 10,
                       max_threads               INTEGER DEFAULT 3,
                       time_between_questions_ms INTEGER DEFAULT 2000,
                       end_time_s                INTEGER DEFAULT 60,
                       random_delta_delay        INTEGER DEFAULT 0,
                       random_delta_timeout      INTEGER DEFAULT 0,
                       scan_interval             INTEGER DEFAULT 500,
                       error_cooldown            INTEGER DEFAULT 3000,
                       success_cooldown          INTEGER DEFAULT 3000
                   )
                   ''')

    cursor.execute('SELECT count(*) FROM settings')
    if cursor.fetchone()[0] == 0:
        cursor.execute(
            '''INSERT INTO settings (id, percent_message, percent_special, max_threads, time_between_questions_ms,
                                     end_time_s, random_delta_delay, random_delta_timeout, scan_interval, error_cooldown, success_cooldown)
                          VALUES (1, 50, 10, 3, 2000, 60, 0, 0, 500, 3000, 3000)''')
    else:
        # Migration: Add new columns if missing
        cursor.execute("PRAGMA table_info(settings)")
        cols = [c[1] for c in cursor.fetchall()]
        if 'scan_interval' not in cols: cursor.execute("ALTER TABLE settings ADD COLUMN scan_interval INTEGER DEFAULT 500")
        if 'error_cooldown' not in cols: cursor.execute("ALTER TABLE settings ADD COLUMN error_cooldown INTEGER DEFAULT 3000")
        if 'success_cooldown' not in cols: cursor.execute("ALTER TABLE settings ADD COLUMN success_cooldown INTEGER DEFAULT 3000")
        # Ensure previous columns exist too (just in case)
        if 'max_threads' not in cols: cursor.execute("ALTER TABLE settings ADD COLUMN max_threads INTEGER DEFAULT 3")

    conn.commit()
    conn.close()

init_db()

# --- HELPER: TIME RANGES ---
def get_shift_bounds(dt):
    h = dt.hour; date_part = dt.date()
    if 6 <= h < 14: return datetime.datetime.combine(date_part, datetime.time(6,0)), datetime.datetime.combine(date_part, datetime.time(13,59,59))
    elif 14 <= h < 22: return datetime.datetime.combine(date_part, datetime.time(14,0)), datetime.datetime.combine(date_part, datetime.time(21,59,59))
    else:
        if h >= 22: return datetime.datetime.combine(date_part, datetime.time(22,0)), datetime.datetime.combine(date_part + timedelta(days=1), datetime.time(5,59,59))
        else: return datetime.datetime.combine(date_part - timedelta(days=1), datetime.time(22,0)), datetime.datetime.combine(date_part, datetime.time(5,59,59))

def get_time_range(filter_type):
    now = datetime.datetime.now()
    if filter_type == 'month': return now.replace(day=1, hour=0, minute=0, second=0), now.replace(hour=23, minute=59, second=59)
    elif filter_type == 'this_shift': return get_shift_bounds(now)
    elif filter_type == 'last_shift': return get_shift_bounds(now - timedelta(hours=8))
    elif filter_type == 'yesterday': y = now - timedelta(days=1); return y.replace(hour=0,minute=0,second=0), y.replace(hour=23,minute=59,second=59)
    else: return now.replace(hour=0,minute=0,second=0), now.replace(hour=23,minute=59,second=59)

# --- CORE FUNCTIONS ---
def decode_image(image_data):
    try:
        encoded_data = image_data.split(',')[1] if ',' in image_data else image_data
        nparr = np.frombuffer(base64.b64decode(encoded_data), np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        decoded_texts = reader.detect_and_decode(image=img)
        if decoded_texts and decoded_texts[0] is not None: return decoded_texts[0]
        return None
    except: return None

def check_if_exists(code):
    try:
        conn = sqlite3.connect(DB_NAME)
        res = conn.execute("SELECT id FROM scans WHERE code = ?", (code,)).fetchone()
        conn.close()
        return res is not None
    except: return False

def save_scan_to_db(code, is_valid, error_msg):
    try:
        conn = sqlite3.connect(DB_NAME)
        conn.execute('INSERT INTO scans (code, scanned_time, is_valid, error) VALUES (?, ?, ?, ?)', (code, datetime.datetime.now(), is_valid, error_msg))
        conn.commit()
        conn.close()
    except: pass

# --- ROUTES ---
@app.route('/')
def index(): return render_template('index.html')

@app.route('/scan', methods=['POST'])
def scan():
    data = request.json; img_data = data.get('image')
    if not img_data: return jsonify({'error': 'No image'}), 400
    decoded = decode_image(img_data)
    if decoded:
        is_valid = False; err = None
        if not decoded.startswith(TARGET_PREFIX): err = "Invalid Prefix"
        elif check_if_exists(decoded): err = "Duplicate Code"
        else: is_valid = True
        save_scan_to_db(decoded, is_valid, err)
        return jsonify({'success': True, 'data': decoded, 'is_valid': is_valid, 'error': err})
    return jsonify({'success': False})

@app.route('/get_logs', methods=['GET'])
def get_logs():
    try:
        time_filter = request.args.get('time_filter', 'today')
        start_dt, end_dt = get_time_range(time_filter)
        conn = sqlite3.connect(DB_NAME); conn.row_factory = sqlite3.Row

        stat_scanned = conn.execute("SELECT COUNT(*) FROM scans WHERE scanned_time >= ? AND scanned_time <= ?", (start_dt, end_dt)).fetchone()[0]
        stat_success = conn.execute("SELECT COUNT(*) FROM scans WHERE processing_successful = 1 AND scanned_time >= ? AND scanned_time <= ?", (start_dt, end_dt)).fetchone()[0]
        stat_pending = conn.execute("SELECT COUNT(*) FROM scans WHERE is_valid = 1 AND processing_successful IS NULL AND scanned_time >= ? AND scanned_time <= ?", (start_dt, end_dt)).fetchone()[0]
        stat_errored = conn.execute("SELECT COUNT(*) FROM scans WHERE (is_valid = 0 OR processing_successful = 0) AND scanned_time >= ? AND scanned_time <= ?", (start_dt, end_dt)).fetchone()[0]
        logs = [dict(r) for r in conn.execute("SELECT * FROM scans WHERE scanned_time >= ? AND scanned_time <= ? ORDER BY scanned_time DESC", (start_dt, end_dt)).fetchall()]
        conn.close()
        return jsonify({'success': True, 'stats': {'scanned': stat_scanned, 'success': stat_success, 'pending': stat_pending, 'errored': stat_errored}, 'logs': logs})
    except Exception as e: return jsonify({'success': False, 'error': str(e)})

@app.route('/settings', methods=['GET', 'POST'])
def handle_settings():
    conn = sqlite3.connect(DB_NAME); conn.row_factory = sqlite3.Row
    if request.method == 'GET':
        row = conn.execute('SELECT * FROM settings WHERE id = 1').fetchone()
        conn.close()
        # Fallback defaults if new columns are None (migration safety)
        d = dict(row)
        return jsonify(d)

    d = request.json
    conn.execute('''UPDATE settings SET
                                        percent_message=?, percent_special=?, max_threads=?, time_between_questions_ms=?, end_time_s=?, random_delta_delay=?, random_delta_timeout=?,
                                        scan_interval=?, error_cooldown=?, success_cooldown=?
                    WHERE id = 1''', (
                     d['percent_message'], d['percent_special'], d.get('max_threads', 3),
                     d.get('time_between_questions_ms', 2000), d.get('end_time_s', 60),
                     d.get('random_delta_delay', 0), d.get('random_delta_timeout', 0),
                     d.get('scan_interval', 500), d.get('error_cooldown', 3000), d.get('success_cooldown', 3000)
                 ))
    conn.commit(); conn.close()
    return jsonify({'success': True})

@app.route('/get_messages', methods=['GET'])
def get_messages():
    conn = sqlite3.connect(DB_NAME); conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM messages ORDER BY id DESC").fetchall()
    conn.close()
    return jsonify({'success': True, 'messages': [dict(r) for r in rows]})

@app.route('/add_message', methods=['POST'])
def add_message():
    d = request.json
    conn = sqlite3.connect(DB_NAME)
    conn.execute('INSERT INTO messages (text, is_reusable, times_used, enabled) VALUES (?, ?, 0, ?)', (d['text'], d.get('is_reusable', False), d.get('enabled', True)))
    conn.commit(); conn.close()
    return jsonify({'success': True})

@app.route('/delete_message/<int:id>', methods=['DELETE'])
def delete_message(id):
    conn = sqlite3.connect(DB_NAME); conn.execute('DELETE FROM messages WHERE id = ?', (id,)); conn.commit(); conn.close()
    return jsonify({'success': True})

@app.route('/update_message/<int:id>', methods=['PUT'])
def update_message(id):
    d = request.json; conn = sqlite3.connect(DB_NAME)
    conn.execute('UPDATE messages SET text=?, is_reusable=?, enabled=? WHERE id=?', (d['text'], d.get('is_reusable'), d.get('enabled'), id))
    conn.commit(); conn.close()
    return jsonify({'success': True})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)