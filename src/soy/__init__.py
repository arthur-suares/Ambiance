"""Camada de análise estruturada para a cadeia produtiva da soja brasileira."""

from .catalog import DEFAULT_SOY_MANIFEST, ensure_manifest, load_manifest
from .ingest import detect_missing_datasets, ingest_soy_datasets, profile_file
from .queries import (
    deforestation_by_biome,
    exposure_by_municipality,
    top_destinations,
    top_exporters,
    top_municipalities,
    yearly_trend,
)
from .routing import route_question

__all__ = [
    "DEFAULT_SOY_MANIFEST",
    "ensure_manifest",
    "load_manifest",
    "profile_file",
    "detect_missing_datasets",
    "ingest_soy_datasets",
    "top_municipalities",
    "top_exporters",
    "top_destinations",
    "yearly_trend",
    "exposure_by_municipality",
    "deforestation_by_biome",
    "route_question",
]
