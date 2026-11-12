"""Локальный расчёт эмбеддингов multilingual-e5-small на CPU."""

from functools import lru_cache
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

from app.core.config import settings


class EmbeddingUnavailableError(Exception):
    pass


@lru_cache(maxsize=1)
def load_model():
    directory = Path(settings.EMBEDDING_MODEL_DIR)
    tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
    tokenizer.enable_truncation(max_length=512)
    tokenizer.enable_padding(pad_id=tokenizer.token_to_id("<pad>"), pad_token="<pad>")

    options = ort.SessionOptions()
    options.intra_op_num_threads = 2
    session = ort.InferenceSession(
        str(directory / "model_int8.onnx"),
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )
    return tokenizer, session


def embed(texts: list[str], *, kind: str) -> list[list[float]]:
    try:
        tokenizer, session = load_model()
        vectors = []
        for start in range(0, len(texts), 16):
            batch = tokenizer.encode_batch([f"{kind}: {text}" for text in texts[start:start + 16]])
            mask = np.asarray([item.attention_mask for item in batch], dtype=np.int64)
            inputs = {
                "input_ids": np.asarray([item.ids for item in batch], dtype=np.int64),
                "attention_mask": mask,
                "token_type_ids": np.asarray([item.type_ids for item in batch], dtype=np.int64),
            }
            (hidden,) = session.run(
                ["last_hidden_state"], {item.name: inputs[item.name] for item in session.get_inputs()}
            )
            # Усредняем только токены текста и нормализуем вектор для поиска.
            pooled = (hidden * mask[..., None]).sum(axis=1) / mask.sum(axis=1, keepdims=True)
            pooled /= np.linalg.norm(pooled, axis=1, keepdims=True)
            vectors.extend(pooled.tolist())
        return vectors
    except Exception as error:
        # Библиотеки токенизации и ONNX используют разные типы исключений.
        raise EmbeddingUnavailableError(type(error).__name__) from error
