"""Dynamic Crypto & Hash Signature Sniffer."""
import re
from typing import Dict, Any, List, Optional

SIGNATURE_PARAM_PATTERNS = [
    re.compile(r"^(w_)?rid$", re.IGNORECASE),
    re.compile(r"^_?sign(ature)?$", re.IGNORECASE),
    re.compile(r"^token$", re.IGNORECASE),
    re.compile(r"^hash$", re.IGNORECASE),
    re.compile(r"^_t$", re.IGNORECASE),
    re.compile(r"^ts$", re.IGNORECASE),
    re.compile(r"^timestamp$", re.IGNORECASE),
]

HEX_32_PATTERN = re.compile(r"^[a-fA-F0-9]{32}$")
HEX_64_PATTERN = re.compile(r"^[a-fA-F0-9]{64}$")
TIMESTAMP_PATTERN = re.compile(r"^\d{10}(\d{3})?$")  # 10 or 13 digits


def sniff_request_signatures(params: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Sniff candidate dynamic hash signatures and timestamps from query or post params.
    Returns list of detected suspicious signature parameters with their type.
    """
    detected: List[Dict[str, str]] = []

    for k, v in params.items():
        v_str = str(v).strip()
        key_matched = any(p.match(k) for p in SIGNATURE_PARAM_PATTERNS)

        if TIMESTAMP_PATTERN.match(v_str) or k.lower() in ("t", "ts", "timestamp", "_t"):
            detected.append({"param": k, "value": v_str, "type": "timestamp"})
            continue

        if HEX_32_PATTERN.match(v_str):
            detected.append({"param": k, "value": v_str, "type": "hex32_md5"})
            continue

        if HEX_64_PATTERN.match(v_str):
            detected.append({"param": k, "value": v_str, "type": "hex64_sha256"})
            continue

        if key_matched:
            detected.append({"param": k, "value": v_str, "type": "named_signature"})

    return detected


def is_signature_mismatch_error(stderr_text: str) -> bool:
    """Check if sandbox execution failure is caused by signature/token verification error."""
    t = stderr_text.lower()
    indicators = [
        "sign error",
        "signature error",
        "invalid signature",
        "invalid token",
        "token expired",
        "-400",
        "illegal request",
        "signature verification failed",
    ]
    return any(ind in t for ind in indicators)
