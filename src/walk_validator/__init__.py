"""Fase 2 — validación empírica del catálogo contra snmpwalks reales."""
from .walk_validator import (WalkValidator, detect_vendor_family,
                             detect_walk_type, model_key)

__all__ = ["WalkValidator", "detect_vendor_family", "detect_walk_type", "model_key"]
