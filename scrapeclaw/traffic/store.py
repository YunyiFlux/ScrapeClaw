"""ScrapeClaw Traffic Store & Persistence."""
import json
import hashlib
from pathlib import Path
from typing import Optional, List
from scrapeclaw.traffic.models import TrafficRecord, RequestSnapshot, ResponseSnapshot

class TrafficStore:
    def __init__(self, workspace_dir: Path):
        self.workspace_dir = workspace_dir
        self.traffic_dir = workspace_dir / "traffic"
        self.raw_dir = self.traffic_dir / "raw"
        self.index_file = self.traffic_dir / "traffic_index.jsonl"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        self.records: list[TrafficRecord] = []
        self._seq = 0

    def record_traffic(
        self,
        resource_type: str,
        request: RequestSnapshot,
        status_code: int,
        response_headers: dict[str, str],
        response_body: bytes,
        content_type: str = "application/json"
    ) -> TrafficRecord:
        self._seq += 1
        record_id = f"t{self._seq:03d}"
        
        # Save raw body to disk
        body_hash = hashlib.sha256(response_body).hexdigest()[:16]
        raw_file = self.raw_dir / f"{record_id}_resp.bin"
        raw_file.write_bytes(response_body)

        response_snapshot = ResponseSnapshot(
            status_code=status_code,
            headers=response_headers,
            content_type=content_type,
            body_length=len(response_body),
            raw_file_path=str(raw_file.relative_to(self.workspace_dir)),
            content_hash=body_hash
        )

        record = TrafficRecord(
            id=record_id,
            resource_type=resource_type,
            request=request,
            response=response_snapshot
        )

        self.records.append(record)
        
        # Append to JSONL index
        with open(self.index_file, "a", encoding="utf-8") as f:
            f.write(record.model_dump_json() + "\n")

        return record

    def get_record(self, traffic_id: str) -> Optional[TrafficRecord]:
        for r in self.records:
            if r.id == traffic_id:
                return r
        return None

    def read_raw_response(self, record: TrafficRecord) -> bytes:
        if not record.response or not record.response.raw_file_path:
            return b""
        file_path = self.workspace_dir / record.response.raw_file_path
        if file_path.exists():
            return file_path.read_bytes()
        return b""
