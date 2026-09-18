"""Base classes and flattening utilities for data exporters."""
import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import List, Dict, Any


def flatten_dict(d: Dict[str, Any], parent_key: str = "", sep: str = ".") -> Dict[str, Any]:
    """
    Recursively flatten a nested dictionary for tabular/columnar serialization.
    E.g. {"author": {"name": "Alice"}} -> {"author.name": "Alice"}
    Lists of primitives are serialized to JSON string or joined.
    """
    items: List[tuple] = []
    for k, v in d.items():
        new_key = f"{parent_key}{sep}{k}" if parent_key else k
        if isinstance(v, dict):
            items.extend(flatten_dict(v, new_key, sep=sep).items())
        elif isinstance(v, list):
            items.append((new_key, json.dumps(v, ensure_ascii=False)))
        else:
            items.append((new_key, v))
    return dict(items)


class DataExporterBase(ABC):
    """Abstract base class for all data export formats."""

    @abstractmethod
    def export(self, data: List[Dict[str, Any]], target_path: Path) -> Path:
        """
        Export list of dictionary records to target path.
        Returns the resolved Path of the written file.
        """
        pass
