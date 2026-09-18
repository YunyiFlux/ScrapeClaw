"""ScrapeClaw Traffic Models."""
from __future__ import annotations
import hashlib
import json
from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field, ConfigDict

class RequestSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    url: str
    method: str = "GET"
    headers: dict[str, str] = Field(default_factory=dict)
    cookies: dict[str, str] = Field(default_factory=dict)
    query_params: dict[str, Any] = Field(default_factory=dict)
    post_data: Optional[str] = None
    json_body: Optional[Any] = None

    @property
    def fingerprint(self) -> str:
        content = f"{self.method}:{self.url}:{json.dumps(self.query_params, sort_keys=True)}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

class ResponseSnapshot(BaseModel):
    model_config = ConfigDict(frozen=True)
    status_code: int
    headers: dict[str, str] = Field(default_factory=dict)
    content_type: str = ""
    body_length: int = 0
    raw_file_path: str = ""
    content_hash: str = ""

class TrafficRecord(BaseModel):
    id: str
    timestamp: str = Field(default_factory=lambda: datetime.now().isoformat())
    resource_type: str = "xhr"
    request: RequestSnapshot
    response: Optional[ResponseSnapshot] = None
    is_candidate: bool = False
    match_score: float = 0.0
    matched_keys: list[str] = Field(default_factory=list)
