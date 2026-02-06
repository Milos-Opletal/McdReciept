import sqlite3
import time
import random
import concurrent.futures
import logging
import datetime
from playwright.sync_api import Playwright, sync_playwright, expect  # Updated Import

# Configuration
DB_NAME = "scans.db"
POLL_INTERVAL = 5

# Logging Setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - WORKER - %(message)s')


def get_db_connection():
    conn = sqlite3.connect(DB_NAME)
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
def process_valid_code(code, base_delay, delta_delay, base_timeout, delta_timeout, message):
    """
    Main automation function using Playwright.
    """

    # Calculate actual parameters
    actual_delay = base_delay + random.randint(0, delta_delay)
    actual_timeout = base_timeout + random.randint(0, delta_timeout)

    logging.info(f"--> START Processing: {code}")
    logging.info(
        f"    Params: BaseDelay={base_delay}ms (Delta={delta_delay}), BaseTimeout={base_timeout}s (Delta={delta_timeout})")
    logging.info(f"    Actual Used: Delay={actual_delay}ms, Timeout={actual_timeout}s")
    logging.info(f"    Message: '{message}'")

    # ----------------------------------------------------
    # PLAYWRIGHT AUTOMATION LOGIC GOES HERE
    # ----------------------------------------------------
    # Example structure:
    # with sync_playwright() as p:
    #     browser = p.chromium.launch(headless=True)
    #     page = browser.new_page()
    #     # Use expect(page.locator(...)).to_be_visible()
    #     # ... actions ...
    #     browser.close()

    # Simulation for now
    time.sleep(random.uniform(1.0, 3.0))

    # Simulate error for testing if needed
    # if random.randint(1, 10) > 8: raise Exception("Random Playwright Error")

    return True


def worker_task(scan_id, code):
    """
    Refetches settings immediately to ensure freshness, then processes.
    Catches errors from process_valid_code and saves them to DB.
    """
    try:
        # 1. REFETCH SETTINGS
        settings = get_settings()

        # 2. Get Message
        msg_text, _ = get_message(settings['percent_message'], settings['percent_special'])

        success = False
        error_msg = None

        # 3. Run Process with Error Handling
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
            logging.error(f"Process failed for {code}: {process_error}")

        # 4. Update DB (Including Error Message)
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

        status_log = "Success" if success else f"Failed ({error_msg})"
        logging.info(f"<-- DONE Processing: {code} | {status_log}")

    except Exception as e:
        logging.error(f"Critical Worker Task Error on ID {scan_id}: {e}")


def main():
    ensure_settings_column()
    logging.info("Worker started.")

    while True:
        try:
            conn = get_db_connection()
            pending = conn.execute(
                "SELECT id, code FROM scans WHERE is_valid = 1 AND processing_successful IS NULL ORDER BY scanned_time ASC").fetchall()
            conn.close()

            pending_count = len(pending)

            if pending_count > 0:
                settings = get_settings()

                # Logic: 1 thread per 10 codes, clamped by max_threads (Range 1-3)
                calc_threads = (pending_count // 10) + 1
                max_threads = max(1, min(3, settings['max_threads']))
                num_threads = min(calc_threads, max_threads)

                logging.info(f"Pending: {pending_count}. Threads: {num_threads} (Max allowed: {max_threads})")

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