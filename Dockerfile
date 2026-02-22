# ============================================
# NextChord - Hugging Face Spaces Dockerfile
# ============================================

# --- Stage 1: Build Frontend ---
FROM node:20-slim AS frontend-builder
WORKDIR /build
COPY nextchord-ui/package*.json ./
RUN npm ci
COPY nextchord-ui/ ./
# Production build - API calls go to same origin
ENV VITE_API_URL=""
RUN npm run build

# --- Stage 2: Backend + Serve Frontend ---
FROM python:3.12-slim

# System dependencies
RUN apt-get update && apt-get install -y \
    ffmpeg \
    libsndfile1 \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Python dependencies (Cython + numpy needed for madmom build)
COPY requirements.txt .
RUN pip install --no-cache-dir Cython numpy setuptools wheel && \
    pip install --no-cache-dir --no-build-isolation madmom && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir torch torchaudio --index-url https://download.pytorch.org/whl/cpu && \
    pip install --no-cache-dir openai-whisper && \
    pip install --no-cache-dir demucs && \
    pip install --no-cache-dir onnxruntime && \
    pip install --no-cache-dir --no-deps basic-pitch && \
    pip install --no-cache-dir yt-dlp && \
    pip install --no-cache-dir setuptools

# Copy backend code
COPY fastapi-backend/ ./fastapi-backend/

# Copy built frontend from Stage 1
COPY --from=frontend-builder /build/dist ./frontend-dist/

# Create uploads directory
RUN mkdir -p /app/uploads

# Copy any .env if exists (optional)
COPY .env* ./

# Create non-root user (HF Spaces requirement)
RUN useradd -m -u 1000 user && \
    chown -R user:user /app
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH

# HF Spaces uses port 7860
ENV PORT=7860
EXPOSE 7860

WORKDIR /app/fastapi-backend

# Run the application
CMD ["python", "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "7860"]
