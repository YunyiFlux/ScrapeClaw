# -*- coding: utf-8 -*-
"""Base Scaffolder Interface."""
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Dict, Any


class BaseScaffolder(ABC):
    """Abstract base class for crawler scaffolders."""

    @abstractmethod
    def generate(self, spec: Dict[str, Any], output_path: Path) -> Dict[str, Path]:
        """Generate crawler script or project files.

        Args:
            spec: Extracted reverse-engineering specification.
            output_path: Target file or project directory.

        Returns:
            Dict mapping relative file path strings to generated Path objects.
        """
        pass
