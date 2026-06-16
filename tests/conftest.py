"""Shared test config — force the deterministic hash embedding backend so the
unit suite needs no model downloads, DB, or network."""
import os

os.environ.setdefault("EMBED_BACKEND", "hash")
os.environ.setdefault("DATABASE_URL", "postgresql://postgres:postgres@localhost:5432/prodrescue_test")
