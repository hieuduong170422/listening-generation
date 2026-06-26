FROM python:3.12-slim

# ffmpeg: pydub (ghép/encode audio) + video_builder (xuất .mp4) cần binary này.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# Cài deps trước (tách layer để tận dụng cache khi chỉ đổi code).
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy phần còn lại của app.
COPY . .

# Cloud Run cấp PORT qua env (mặc định 8080). Local fallback về 8080.
ENV PORT=8080
EXPOSE 8080

# Bind 0.0.0.0:$PORT; tắt CORS/XSRF cho môi trường sau proxy của Cloud Run.
CMD streamlit run app.py \
    --server.port=${PORT} \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --server.enableCORS=false \
    --server.enableXsrfProtection=false \
    --browser.gatherUsageStats=false
