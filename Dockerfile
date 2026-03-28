FROM python:3.10-slim

# Prevent Python from generating .pyc files and buffering stdout
# Added TZ variable here for central management
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright \
    TZ=Europe/Prague

WORKDIR /app

# 1. Install base tools, libraries, and TZDATA
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    libzbar0 \
    curl \
    tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# 2. FIX: Install CPU-only Torch AND Torchvision first
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

# 3. Install remaining Python packages
RUN pip install --no-cache-dir \
    flask \
    qreader \
    opencv-python-headless \
    playwright \
    numpy \
    gunicorn

# 4. Install Browsers (Chromium, Firefox, WebKit)
RUN playwright install --with-deps \
    && rm -rf /var/lib/apt/lists/*

COPY . .

CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:5000", "app:app"]