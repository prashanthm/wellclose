# LiteLLM gateway + Pillow. The upstream image ships without PIL, but LiteLLM needs it to
# convert page images for Ollama's vision models (qwen2.5vl) — without it every image-bearing
# request 500s with "ollama image conversion failed please run `pip install Pillow`".
FROM ghcr.io/berriai/litellm:v1.88.1
# The image's venv at /app/.venv ships no pip/uv on PATH; bootstrap pip via ensurepip, add Pillow.
RUN /app/.venv/bin/python -m ensurepip --upgrade \
 && /app/.venv/bin/python -m pip install --no-cache-dir Pillow
