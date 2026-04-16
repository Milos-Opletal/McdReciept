# 🍔 McdReceipt — McDonald's Receipt QR Scanner & Survey Automator

A self-hosted web application that scans QR codes from McDonald's receipts and automatically fills out the associated customer feedback surveys via browser automation.

## How It Works

The app runs as two services sharing the same Docker image:

1. **Web** (`app.py`) — A Flask web server that provides a camera-based QR code scanner UI. You point your phone or webcam at a McDonald's receipt, the app detects the QR code, validates it, and stores it in a SQLite database.
2. **Worker** (`worker.py`) — A background process that polls the database for new scans and uses Playwright (headless Chromium) to automatically navigate through the McDonald's feedback survey, fill in responses, and submit.

### Features

- 📷 **Live camera QR scanning** directly from the browser
- ✅ **Automatic duplicate detection** — won't process the same code twice
- 🤖 **Automated survey completion** with configurable delays and timeouts
- 💬 **Custom messages** — attach reusable or one-time messages to survey submissions
- 📊 **Dashboard with logs & stats** — filter by today, current shift, last shift, or month
- ⚙️ **Settings panel** — configure thread count, delays, cooldowns, and message probability
- 🐳 **Fully Dockerized** — single image, two-service deployment via Docker Compose

## Prerequisites

- **Docker** and **Docker Compose** installed on the host machine
- A machine with at least **2 GB of RAM** (Playwright + PyTorch run in-container)
- Network access to `mcdonalds.fast-insight.com` (the survey endpoint)

## Quick Start

### 1. Clone the repository

```bash
git clone https://github.com/Milos-Opletal/McdReciept2.git
cd McdReciept2
```

### 2. Build the Docker image

```bash
docker build -t mcd_qr .
```

### 3. Configure volumes

Edit `docker-compose.yml` and update the volume path to a directory on your host where the SQLite database will be persisted:

```yaml
volumes:
  - /your/host/path:/app/db
```

### 4. Start the services

```bash
docker compose up -d
```

This starts both the **web UI** and the **background worker**.

### 5. Open the scanner

Navigate to `http://<your-host-ip>:5005` in your browser. Allow camera access when prompted, then start scanning receipts.

## Project Structure

```
McdReciept2/
├── app.py                 # Flask web server (QR scanning, API, dashboard)
├── worker.py              # Background worker (Playwright survey automation)
├── Dockerfile             # Multi-purpose image (web + worker)
├── docker-compose.yml     # Two-service deployment config
├── get_ico.py             # Helper script to download the favicon
├── templates/
│   └── index.html         # Single-page UI (scanner, logs, settings, messages)
├── static/
│   └── favicon.svg        # McDonald's-themed favicon
├── db/                    # SQLite database directory (mounted volume)
└── .dockerignore
```

## Configuration

All settings are configurable from the **Settings** tab in the web UI:

| Setting | Default | Description |
|---|---|---|
| Max Threads | 3 | Concurrent survey submissions |
| Delay Between Questions | 2000 ms | Base delay between survey answers |
| End Time | 60 s | Wait time before final submission |
| Random Delta (Delay) | 0 ms | Randomization added to delay |
| Random Delta (Timeout) | 0 s | Randomization added to end time |
| Message Probability | 50% | Chance of attaching a message |
| Special Message Probability | 10% | Chance of using a one-time message |
| Scan Interval | 500 ms | Camera scan polling interval |
| Error / Success Cooldown | 3000 ms | UI feedback display duration |

## License

This project is provided as-is for personal and educational use.
