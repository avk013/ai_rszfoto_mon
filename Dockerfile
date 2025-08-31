FROM python:3.11-slim

WORKDIR /app


RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libjpeg-dev zlib1g-dev \
    libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt
COPY yolov8m.pt .
COPY . .
RUN mkdir -p /data/inbox /data/filtered /data/rejected

CMD ["xvfb-run", "--auto-servernum", "--server-args='-screen 0 1280x1024x24'", "python", "detect_cars.py"]
