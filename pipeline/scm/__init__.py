"""Supplementary Cementitious Materials (SCM) offline pipeline.

Parallel to the carbon-capture workflow. Seed-category pipelines and an
open-ended discovery branch share corpus, retrieval, LLM, and IO helpers
from the parent ``pipeline`` package without altering carbon-capture behavior.
"""

from pipeline.scm.seed_categories import SCM_SEED_CATEGORIES, list_seed_category_ids

__all__ = [
    "SCM_SEED_CATEGORIES",
    "list_seed_category_ids",
]
