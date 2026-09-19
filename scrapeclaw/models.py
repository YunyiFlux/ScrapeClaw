import asyncio
import concurrent.futures
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from scrapeclaw.exceptions import ExecutionGateError


class SynthesizedCrawler(BaseModel):
    """ScrapeClaw synthesized crawler deliverable and metadata."""
    code: str = Field(..., description="Synthesized Python crawler source code")
    sign_code: Optional[str] = Field(None, description="Decoupled Node.js dynamic sign code if reverse-engineered")
    engine: str = Field("httpx", description="Crawler engine type: httpx, scrapy, drission")
    target_url: str = Field(..., description="Original target webpage URL")
    target_api_url: Optional[str] = Field(None, description="Underlying private API URL discovered")
    target_api_method: str = Field("GET", description="HTTP method of the underlying API")
    minimal_headers: Dict[str, str] = Field(default_factory=dict, description="Pruned minimal headers")
    sample_data: List[Dict[str, Any]] = Field(default_factory=list, description="Sample data verified during sandboxed execution")
    is_verified: bool = Field(True, description="Whether code passed offline physical execution gate")
    steps_taken: int = Field(0, description="Steps taken by solver agent")
    elapsed_seconds: float = Field(0.0, description="Total execution time in seconds")

    def save(self, script_path: str | Path, sign_path: Optional[str | Path] = None) -> Path:
        target = Path(script_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(self.code, encoding="utf-8")
        if self.sign_code:
            sign_file = Path(sign_path).resolve() if sign_path else target.parent / "sign.js"
            sign_file.parent.mkdir(parents=True, exist_ok=True)
            sign_file.write_text(self.sign_code, encoding="utf-8")
        return target

    async def run_async(self, timeout: float = 30.0) -> List[Dict[str, Any]]:
        from scrapeclaw.gate.execution_gate import run_standalone_execution_gate
        with tempfile.TemporaryDirectory() as td:
            temp_p = Path(td) / "spider.py"
            temp_p.write_text(self.code, encoding="utf-8")
            if self.sign_code:
                (Path(td) / "sign.js").write_text(self.sign_code, encoding="utf-8")

            success, err, items = await run_standalone_execution_gate(str(temp_p), timeout_seconds=timeout)
            if not success:
                raise ExecutionGateError(f"Crawler execution failed: {err}")
            return items

    def run(self, timeout: float = 30.0) -> List[Dict[str, Any]]:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    return pool.submit(lambda: asyncio.run(self.run_async(timeout=timeout))).result()
            else:
                return loop.run_until_complete(self.run_async(timeout=timeout))
        except RuntimeError:
            return asyncio.run(self.run_async(timeout=timeout))

    def to_dict(self) -> Dict[str, Any]:
        return self.model_dump()
