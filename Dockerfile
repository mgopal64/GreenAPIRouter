FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 HF_HOME=/app/.hf PORT=8080
WORKDIR /app

# torch first, from the CPU-only index. PyPI's torch bundles ~2 GB of CUDA libraries.
RUN pip install torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu

# Everything else. torch is already satisfied, so pip leaves it alone.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Non-root user that owns the model cache. Created before the download
# so we never have to chown a large directory, which would duplicate it in a new layer.
RUN useradd -m -u 1000 app && mkdir -p /app/.hf && chown app /app/.hf
USER app

# Bake the weights in at the pinned revisions. Skip TensorFlow/Flax files we don't use.
ARG REPO_REVISION="fea1121511eafabaf7dd6fc66863dcb04f74defb"
ARG BACKBONE_REVISION="8ccc9b6f36199bec6961081d44eb72fb3f7353f3"
RUN python -c "from huggingface_hub import snapshot_download as d; \
p=['*.json','*.safetensors','*.bin','*.model','*.txt']; \
d('nvidia/prompt-task-and-complexity-classifier', revision='${REPO_REVISION}', allow_patterns=p); \
d('microsoft/DeBERTa-v3-base', revision='${BACKBONE_REVISION}', allow_patterns=p)"

# Code last, because it changes most often.
COPY --chown=app greenrouter/ greenrouter/

# Never reach out to Hugging Face at runtime. If the bake missed a file, fail loudly now, not in production.
ENV HF_HUB_OFFLINE=1
CMD exec uvicorn greenrouter.main:app --host 0.0.0.0 --port ${PORT}