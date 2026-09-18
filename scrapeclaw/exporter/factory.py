"""Exporter factory with automatic format deduction."""
from pathlib import Path
from typing import Optional
from scrapeclaw.exporter.base import DataExporterBase
from scrapeclaw.exporter.formats import JsonExporter, JsonlExporter, CsvExporter


def get_exporter(format_name: Optional[str] = None, file_path: Optional[Path] = None) -> DataExporterBase:
    """
    Resolve exporter instance by explicit format name or target file extension.
    Supported: 'json', 'jsonl', 'csv'. Default: 'json'.
    """
    resolved = "json"

    if format_name:
        resolved = format_name.lower().strip()
    elif file_path:
        ext = file_path.suffix.lower()
        if ext == ".csv":
            resolved = "csv"
        elif ext in (".jsonl", ".ndjson"):
            resolved = "jsonl"
        elif ext == ".json":
            resolved = "json"

    if resolved == "csv":
        return CsvExporter()
    elif resolved in ("jsonl", "ndjson"):
        return JsonlExporter()
    else:
        return JsonExporter()
