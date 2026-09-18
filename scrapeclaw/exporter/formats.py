"""Concrete Exporters for JSON, JSONL, and CSV."""
import csv
import codecs
import json
from pathlib import Path
from typing import List, Dict, Any
from scrapeclaw.exporter.base import DataExporterBase, flatten_dict


class JsonExporter(DataExporterBase):
    """Export records as standard indented JSON array."""

    def export(self, data: List[Dict[str, Any]], target_path: Path) -> Path:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(data, ensure_ascii=False, indent=2)
        target_path.write_text(content, encoding="utf-8")
        return target_path


class JsonlExporter(DataExporterBase):
    """Export records as streaming JSON Lines format (one JSON object per line)."""

    def export(self, data: List[Dict[str, Any]], target_path: Path) -> Path:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        lines = [json.dumps(record, ensure_ascii=False) for record in data]
        target_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return target_path


class CsvExporter(DataExporterBase):
    """
    Export records to CSV with automatic dictionary flattening and
    UTF-8 BOM support for seamless opening in Microsoft Excel on Windows.
    """

    def export(self, data: List[Dict[str, Any]], target_path: Path) -> Path:
        target_path.parent.mkdir(parents=True, exist_ok=True)

        if not data:
            target_path.write_text("", encoding="utf-8-sig")
            return target_path

        # 1. Flatten all records
        flat_records = [flatten_dict(record) for record in data]

        # 2. Extract union of all headers preserving order
        headers: List[str] = []
        for r in flat_records:
            for k in r.keys():
                if k not in headers:
                    headers.append(k)

        # 3. Write with UTF-8 BOM so Excel opens cleanly
        with open(target_path, "w", newline="", encoding="utf-8-sig") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for r in flat_records:
                writer.writerow(r)

        return target_path
