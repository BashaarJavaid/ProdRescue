"""Embedding determinism/dimension and Prometheus metric emission."""
import math
from uuid import uuid4

from prometheus_client import generate_latest
from services.api.embeddings import embed
from services.api.metrics import emit_prometheus_metrics
from services.config import settings
from services.schemas.models import HarnessResult


def test_embed_hash_is_unit_normalised_and_correct_dim():
    v = embed("AttributeError NoneType total")
    assert len(v) == settings.embed_dim
    assert abs(math.sqrt(sum(x * x for x in v)) - 1.0) < 1e-6


def test_embed_hash_is_deterministic():
    assert embed("same text") == embed("same text")
    assert embed("a") != embed("b")


def test_emit_metrics_labels_outcome():
    emit_prometheus_metrics(
        HarnessResult(run_id=uuid4(), passed=True, coverage_delta=1.0,
                      duration_ms=2000, retry_attempt=0),
        service="payments", time_to_pr=12.0,
    )
    emit_prometheus_metrics(
        HarnessResult(run_id=uuid4(), passed=False, coverage_delta=-1.0,
                      duration_ms=500, retry_attempt=3),
        service="payments",
    )
    out = generate_latest().decode()
    assert 'prodrescue_patches_total{outcome="pass",service="payments"}' in out
    assert 'prodrescue_patches_total{outcome="max_retry",service="payments"}' in out
