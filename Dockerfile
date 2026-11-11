FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 EMBEDDING_MODEL_DIR=/opt/embeddings
WORKDIR /app

RUN useradd --create-home --uid 10001 sirius

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

RUN install -d -m 0755 /opt/embeddings
ARG EMBEDDING_REVISION=761b726dd34fb83930e26aab4e9ac3899aa1fa78
ADD --chmod=644 https://huggingface.co/Xenova/multilingual-e5-small/resolve/${EMBEDDING_REVISION}/onnx/model_int8.onnx /opt/embeddings/model_int8.onnx
ADD --chmod=644 https://huggingface.co/Xenova/multilingual-e5-small/resolve/${EMBEDDING_REVISION}/tokenizer.json /opt/embeddings/tokenizer.json

COPY . .
USER sirius
