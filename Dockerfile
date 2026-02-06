FROM python:3.10-slim

# Prevent Python from generating .pyc files and buffering stdout
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

WORKDIR /app

# 1. Install base tools and libraries
RUN apt-get update && apt-get install -y \
    libgl1 \
    libglib2.0-0 \
    libzbar0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 2. FIX: Install CPU-only Torch AND Torchvision first
# We include torchvision here because qreader needs it.
# Installing both from the CPU index prevents pip from downloading NVIDIA CUDA libs later.
RUN pip install --no-cache-dir torch torchvision --index-url https://download.pytorch.org/whl/cpu

# 3. Install remaining Python packages
# qreader will now find the existing CPU torch/torchvision and skip downloading the GPU versions.
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

RUN mkdir -p /app/data && ln -sf /app/data/scans.db /app/scans.db

CMD ["gunicorn", "-w", "1", "-b", "0.0.0.0:5000", "app:app"]