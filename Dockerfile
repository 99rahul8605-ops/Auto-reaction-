# ── Base image ────────────────────────────────────────────────────
FROM python:3.12-slim

# ── System deps ───────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
    && rm -rf /var/lib/apt/lists/*

# ── Working directory ─────────────────────────────────────────────
WORKDIR /app

# ── Install Python dependencies ───────────────────────────────────
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# ── Copy source code ──────────────────────────────────────────────
COPY . .

# ── Expose health-check port ──────────────────────────────────────
EXPOSE 8080

# ── Run the bot ───────────────────────────────────────────────────
CMD ["python", "bot.py"]
