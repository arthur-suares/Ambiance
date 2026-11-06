"""Geração de embeddings com sentence-transformers.

O modelo padrão (intfloat/multilingual-e5-small) foi treinado com prefixos:
- "passage: " para os textos indexados;
- "query: "   para as perguntas.
Usar o prefixo errado (ou nenhum) piora a recuperação de forma silenciosa.
"""

from functools import lru_cache

import numpy as np

from src.config import EMBEDDING_DIM, EMBEDDING_MODEL

_E5 = "e5" in EMBEDDING_MODEL.lower()


@lru_cache(maxsize=1)
def get_model():
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(EMBEDDING_MODEL)
    get_dim = getattr(model, "get_embedding_dimension", None) or model.get_sentence_embedding_dimension
    dim = get_dim()
    if dim != EMBEDDING_DIM:
        raise ValueError(f"{EMBEDDING_MODEL} gera vetores de {dim} dimensões, mas EMBEDDING_DIM={EMBEDDING_DIM}.")
    return model


def max_model_tokens() -> int:
    """Limite de entrada do modelo, lido do próprio modelo (512 no e5-small).

    Textos maiores são truncados sem aviso, por isso o chunking usa este valor
    para garantir que nenhum chunk passe dele. Ler do modelo evita que o limite
    fique errado ao trocar EMBEDDING_MODEL.
    """
    limit = get_model().max_seq_length
    if not limit:
        raise ValueError(f"{EMBEDDING_MODEL} não informa max_seq_length; defina o limite manualmente.")
    return limit


def count_tokens(text: str) -> int:
    """Tokens que o modelo vai enxergar, incluindo o prefixo "passage: "."""
    prefix = "passage: " if _E5 else ""
    return len(get_model().tokenizer.encode(prefix + text, add_special_tokens=True))


def embed_passages(texts: list[str], batch_size: int = 32) -> np.ndarray:
    prefix = "passage: " if _E5 else ""
    return get_model().encode(
        [prefix + t for t in texts],
        batch_size=batch_size,
        normalize_embeddings=True,  # vetores unitários: cosseno = produto interno
        show_progress_bar=len(texts) > batch_size,
    )


def embed_query(text: str) -> np.ndarray:
    prefix = "query: " if _E5 else ""
    return get_model().encode(prefix + text, normalize_embeddings=True)
