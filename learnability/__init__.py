"""Learnability-stage extraction for Learning-Guided Branching for FVS.

Deterministic, standard-library extraction of decision-time candidate features from
Stage C saved branching states, joined to Stage D first-pivot continuation records.
No training, no solver execution, no outcome-based feature selection.
"""
EXTRACTOR_NAME = 'fvs-learnability-extract'
EXTRACTOR_VERSION = '1.0.0'
FEATURE_SCHEMA_VERSION = 'v1'
