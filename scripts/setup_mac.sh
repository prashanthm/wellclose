#!/usr/bin/env bash
# WellClose Mac setup (Brief §16.5 laptop profile). Apple Silicon, 64GB recommended.
set -euo pipefail
command -v brew >/dev/null || { echo "Install Homebrew first: https://brew.sh"; exit 1; }
brew list ollama >/dev/null 2>&1 || brew install ollama
brew list tesseract >/dev/null 2>&1 || brew install tesseract
command -v docker >/dev/null || { echo "Install Docker Desktop or colima"; exit 1; }
brew services start ollama || true
# RAM tiers (§16.5): 36GB -> 7b models only; 64GB -> 32b@4bit; 128GB -> add :72b for headroom checks
ollama pull qwen2.5vl:32b || ollama pull qwen2.5vl:7b
ollama pull qwen2.5:32b   || true
ollama pull qwen2.5:7b
docker compose up -d --wait
pip install -e ".[dev]"
cp -n .env.example .env || true
wellclose init-db
echo "Setup complete. Next: wellclose worker  |  wellclose review-api  |  cd ui && npm install && npm run dev"
