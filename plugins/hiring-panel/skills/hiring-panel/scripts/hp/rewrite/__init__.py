"""Rewrite checks: the deterministic truth check and the provenance gate.

    from hp.rewrite import check_truth, check_provenance
"""
from .truth import check_truth
from .provenance import check_provenance

__all__ = ["check_truth", "check_provenance"]
