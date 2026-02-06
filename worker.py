import sqlite3
import time
import random
import concurrent.futures
import logging
import datetime
import os
from playwright.sync_api import Playwright, sync_playwright, expect

# --- CONFIGURATION ---
DB_FILE_PATH = "scans.db"  # Path to your database
POLL_INTERVAL = 5

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - WORKER - %(message)s')


def get_db_connection():
    """Standard SQLite connection."""
    conn = sqlite3.connect(DB_FILE_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_settings_column():
    """Ensures all required setting columns exist."""
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(settings)")
        columns = [r['name'] for r in cursor.fetchall()]

        # Add missing columns safely
        if 'max_threads' not in columns:
            cursor.execute("ALTER TABLE settings ADD COLUMN max_threads INTEGER DEFAULT 3")
        if 'time_between_questions_ms' not in columns:
            cursor.execute("ALTER TABLE settings ADD COLUMN time_between_questions_ms INTEGER DEFAULT 2000")
        if 'end_time_s' not in columns:
            cursor.execute("ALTER TABLE settings ADD COLUMN end_time_s INTEGER DEFAULT 60")
        if 'random_delta_delay' not in columns:
            cursor.execute("ALTER TABLE settings ADD COLUMN random_delta_delay INTEGER DEFAULT 0")
        if 'random_delta_timeout' not in columns:
            cursor.execute("ALTER TABLE settings ADD COLUMN random_delta_timeout INTEGER DEFAULT 0")
        if 'scan_interval' not in columns:
            cursor.execute("ALTER TABLE settings ADD COLUMN scan_interval INTEGER DEFAULT 500")
        if 'error_cooldown' not in columns:
            cursor.execute("ALTER TABLE settings ADD COLUMN error_cooldown INTEGER DEFAULT 3000")
        if 'success_cooldown' not in columns:
            cursor.execute("ALTER TABLE settings ADD COLUMN success_cooldown INTEGER DEFAULT 3000")

        conn.commit()
        conn.close()
    except Exception as e:
        logging.error(f"Schema check failed: {e}")


def get_settings():
    """Fetches current settings from DB."""
    try:
        conn = get_db_connection()
        row = conn.execute("SELECT * FROM settings WHERE id = 1").fetchone()
        conn.close()
        return {
            'max_threads': row['max_threads'] if row and 'max_threads' in row.keys() else 3,
            'percent_message': row['percent_message'],
            'percent_special': row['percent_special'],
            'base_delay': row[
                'time_between_questions_ms'] if row and 'time_between_questions_ms' in row.keys() else 2000,
            'base_timeout': row['end_time_s'] if row and 'end_time_s' in row.keys() else 60,
            'delta_delay': row['random_delta_delay'] if row and 'random_delta_delay' in row.keys() else 0,
            'delta_timeout': row['random_delta_timeout'] if row and 'random_delta_timeout' in row.keys() else 0
        }
    except Exception as e:
        logging.error(f"Error fetching settings: {e}")
        return {
            'max_threads': 3, 'percent_message': 50, 'percent_special': 10,
            'base_delay': 2000, 'base_timeout': 60, 'delta_delay': 0, 'delta_timeout': 0
        }


def get_message(percent_msg, percent_special):
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM messages WHERE enabled = 1")
        if cursor.fetchone()[0] == 0: return "", None

        if random.randint(1, 100) > percent_msg: return "", None

        is_special = random.randint(1, 100) <= percent_special
        picked_msg, disable_id = None, None

        if is_special:
            cursor.execute("SELECT * FROM messages WHERE is_reusable = 0 AND enabled = 1 ORDER BY RANDOM() LIMIT 1")
            row = cursor.fetchone()
            if row:
                picked_msg, disable_id = row['text'], row['id']
                conn.execute("UPDATE messages SET enabled = 0 WHERE id = ?", (disable_id,))
                conn.commit()
            else:
                is_special = False  # Fallback

        if not is_special:
            cursor.execute("SELECT * FROM messages WHERE is_reusable = 1 AND enabled = 1 ORDER BY RANDOM() LIMIT 1")
            row = cursor.fetchone()
            if row:
                picked_msg = row['text']
                conn.execute("UPDATE messages SET times_used = times_used + 1 WHERE id = ?", (row['id'],))
                conn.commit()

        return picked_msg if picked_msg else "", disable_id
    except Exception as e:
        logging.error(f"Message logic error: {e}")
        return "", None
    finally:
        conn.close()


# --- PROCESSING LOGIC ---
def process_valid_code(code, delay_ms, delay_delta_ms, timeout_s, timeout_delta_s, message):
    """
    Main automation function using Playwright.
    Calculates random values internally.
    """
    # 1. Calculate random values locally
    used_delay_delta = random.randint(0, delay_delta_ms)
    used_timeout_delta = random.randint(0, timeout_delta_s)

    actual_delay = delay_ms + used_delay_delta
    actual_timeout = timeout_s + used_timeout_delta

    # ----------------------------------------------------
    # PLAYWRIGHT AUTOMATION LOGIC GOES HERE
    # ----------------------------------------------------
    # Example structure:
    # with sync_playwright() as p:
    #     browser = p.chromium.launch(headless=True)
    #     page = browser.new_page()
    #     # ... actions ...
    #     browser.close()

    # Simulation
    time.sleep(random.uniform(1.0, 3.0))
    return True


def worker_task(scan_id, code):
    """
    Refetches settings, processes code, and logs result.
    """
    try:
        # 1. REFETCH SETTINGS
        settings = get_settings()

        # 2. GET MESSAGE
        msg_text, _ = get_message(settings['percent_message'], settings['percent_special'])

        success = False
        error_msg = None

        # Minimal Start Log
        logging.info(f"START {code}")

        # 3. RUN PROCESS (Passed raw config values)
        try:
            success = process_valid_code(
                code,
                settings['base_delay'],
                settings['delta_delay'],
                settings['base_timeout'],
                settings['delta_timeout'],
                msg_text
            )
        except Exception as process_error:
            success = False
            error_msg = f"worker error:{str(process_error)}"
            logging.error(f"FAILED {code} | Error: {process_error}")

        # 4. UPDATE DB
        conn = get_db_connection()
        conn.execute("""
                     UPDATE scans
                     SET processed_time        = ?,
                         processing_successful = ?,
                         error                 = ?
                     WHERE id = ?
                     """, (datetime.datetime.now(), success, error_msg, scan_id))
        conn.commit()
        conn.close()

        # Compact Success Log (Logs the Range Config since exact delta is internal)
        if success:
            msg_status = f"Msg: '{msg_text}'" if msg_text else "No Msg"
            logging.info(
                f"DONE {code} | OK | {settings['base_delay']}ms~{settings['delta_delay']} / {settings['base_timeout']}s~{settings['delta_timeout']} | {msg_status}")

    except Exception as e:
        logging.error(f"Critical Worker Task Error on ID {scan_id}: {e}")


def main():
    ensure_settings_column()
    logging.info(f"Worker started. Using DB at: {os.path.abspath(DB_FILE_PATH)}")

    while True:
        try:
            conn = get_db_connection()
            pending = conn.execute(
                "SELECT id, code FROM scans WHERE is_valid = 1 AND processing_successful IS NULL ORDER BY scanned_time ASC").fetchall()
            conn.close()

            pending_count = len(pending)

            if pending_count > 0:
                settings = get_settings()

                # Logic: 1 thread per 10 codes, clamped by max_threads (Range 1-5)
                calc_threads = (pending_count // 10) + 1
                max_threads = max(1, min(5, settings['max_threads']))
                num_threads = min(calc_threads, max_threads)

                logging.info(f"Pending: {pending_count} | Threads: {num_threads}")

                batch = pending[:num_threads]

                with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
                    futures = [executor.submit(worker_task, row['id'], row['code']) for row in batch]
                    concurrent.futures.wait(futures)
            else:
                time.sleep(POLL_INTERVAL)

        except Exception as e:
            logging.error(f"Loop error: {e}")
            time.sleep(5)


if __name__ == "__main__":
    main()