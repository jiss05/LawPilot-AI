# LawPilot backend image (SCRUM-33).
#
# Build and run through docker-compose from the repository root:
#     docker compose up -d --build
#
# The image contains the FastAPI app, Alembic migrations, EasyOCR and
# sentence-transformers. Model files (OCR + embeddings) are downloaded on
# first use into the mounted /models volume, so they survive rebuilds.

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    # Where sentence-transformers / Hugging Face and EasyOCR keep models.
    HF_HOME=/models/huggingface \
    EASYOCR_MODULE_PATH=/models/easyocr

# libgl1 + libglib2.0-0: needed by OpenCV, which EasyOCR uses.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install the CPU-only build of PyTorch first. The default PyPI build for
# Linux includes CUDA libraries (several GB) that a CPU server never uses.
RUN pip install torch torchvision --index-url https://download.pytorch.org/whl/cpu

# Dependencies change less often than code: install them in their own layer
# so code changes rebuild in seconds.
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Run as a normal user, not root.
RUN useradd --create-home --uid 1000 lawpilot \
    && mkdir -p /app/legal_documents /app/storage /models \
    && chown -R lawpilot:lawpilot /app /models \
    && sed -i 's/\r$//' /app/docker-entrypoint.sh \
    && chmod +x /app/docker-entrypoint.sh
USER lawpilot

EXPOSE 8000

# Wait for PostgreSQL, apply migrations, seed roles, then start the API.
ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
