"""Tessera — secure peer-to-peer file sharing built on MFP and madakit.

Public API (ts-spec-010 §2):

    from tessera import TesseraNode, TesseraConfig
"""

from tessera.config import TesseraConfig
from tessera.node import TesseraNode

__all__ = ["TesseraNode", "TesseraConfig"]
