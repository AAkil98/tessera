"""Tessera — secure peer-to-peer file sharing built on MFP and madakit.

Public API (ts-spec-010 §2):

    from tessera import TesseraNode, TesseraConfig, WatchHandle
"""

__version__ = "1.0.0"

from tessera.config import TesseraConfig
from tessera.node import TesseraNode
from tessera.types import WatchHandle

__all__ = ["TesseraNode", "TesseraConfig", "WatchHandle", "__version__"]
