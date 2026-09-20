import urllib.parse
"""JSON Schema Distiller & Deep JSONPath Auto-Extractor."""
from typing import Any, Tuple, List, Dict
import json
import re


def distill_json_structure(data: Any, max_array_sample: int = 1, current_depth: int = 0) -> Any:
    """Distill large arbitrary JSON responses into lightweight schema previews."""
    if current_depth > 6:
        return "...[Max Depth Reached]..."

    if isinstance(data, dict):
        distilled = {}
        for k, v in data.items():
            distilled[k] = distill_json_structure(v, max_array_sample, current_depth + 1)
        return distilled

    elif isinstance(data, list):
        total_len = len(data)
        if total_len == 0:
            return "[]"
        sample = distill_json_structure(data[0], max_array_sample, current_depth + 1)
        return {
            "__type__": f"Array[{total_len}]",
            "sample_item": sample
        }

    elif isinstance(data, str):
        if len(data) > 60:
            return f"{data[:40]}...[len={len(data)}]"
        return data

    else:
        return data


def _score_item_keywords(item_sample: List[Any], goal_keywords: List[str]) -> float:
    """Compute keyword presence score for sample items."""
    if not goal_keywords or not item_sample:
        return 0.0
    text_repr = json.dumps(item_sample, ensure_ascii=False).lower()
    matched = 0
    for kw in goal_keywords:
        kw_clean = kw.strip().lower()
        if not kw_clean:
            continue
        if re.search(r'\b' + re.escape(kw_clean) + r'\b', text_repr):
            matched += 1
    return matched / len(goal_keywords)


def find_best_data_jsonpath(data: Any, goal_keywords: List[str]) -> Tuple[str, float]:
    """
    Search JSON structure to locate the optimal array containing items matching goal keywords.
    Supports flat, nested, and GraphQL-style (edges[*].node) paths.
    
    Returns:
        (best_path, match_score)
    """
    if isinstance(data, list):
        if not data:
            return "", 0.0
        score = _score_item_keywords(data[:3], goal_keywords)
        return "", score

    if not isinstance(data, dict):
        return "", 0.0

    candidates: List[Tuple[str, float, int]] = []  # (path, score, list_length)

    def _traverse(curr: Any, path: str, depth: int = 0):
        if depth > 6:
            return
        
        if isinstance(curr, dict):
            for k, v in curr.items():
                new_path = f"{path}.{k}" if path else k
                _traverse(v, new_path, depth + 1)
                
        elif isinstance(curr, list):
            if len(curr) == 0:
                candidates.append((path, 0.0, 0))
                return
            
            # Check if this list is a GraphQL edge-node wrapper: e.g. [{"node": {...}}, ...]
            first_item = curr[0]
            if isinstance(first_item, dict) and "node" in first_item:
                node_sample = [x.get("node") for x in curr[:5] if isinstance(x, dict) and "node" in x]
                score = _score_item_keywords(node_sample, goal_keywords)
                candidates.append((f"{path}[*].node", score, len(curr)))
            else:
                score = _score_item_keywords(curr[:5], goal_keywords)
                candidates.append((path, score, len(curr)))

    _traverse(data, "", 0)

    if not candidates:
        return "data", 0.0

    # Sort candidates: prioritize highest keyword match score, then non-empty list, then shallower path
    candidates.sort(
        key=lambda c: (
            c[1],                          # match score (higher is better)
            1 if c[2] > 0 else 0,          # non-empty (better)
            -len(c[0].split('.'))          # shorter path (better)
        ),
        reverse=True
    )

    best_path, best_score, _ = candidates[0]
    return best_path, best_score


def score_json_match(data: Any, goal_keywords: List[str]) -> Tuple[float, List[str], str]:
    """
    Score how well a JSON response matches target goal keywords and identify the optimal data path.
    
    Returns:
        (final_score, found_keys, best_data_path)
    """
    found_keys = []
    text_repr = json.dumps(data, ensure_ascii=False).lower()
    
    score = 0.0
    for kw in goal_keywords:
        kw_clean = kw.strip().lower()
        if not kw_clean:
            continue
        if re.search(r'\b' + re.escape(kw_clean) + r'\b', text_repr):
            score += 1.0
            found_keys.append(kw_clean)

    final_score = (score / len(goal_keywords)) if goal_keywords else 0.0
    data_path, _ = find_best_data_jsonpath(data, goal_keywords)

    return min(1.0, final_score), found_keys, data_path


def detect_payload_encryption(data: Any) -> bool:
    """Detect if response content is encrypted ciphertext (e.g. Base64 AES/DES)."""
    if not data:
        return False
    if isinstance(data, bytes):
        try:
            text = data.decode("utf-8").strip()
        except Exception:
            return True
    elif isinstance(data, str):
        text = data.strip()
    else:
        return False

    if text.startswith('"') and text.endswith('"'):
        text = text[1:-1].strip()

    if len(text) > 80 and re.fullmatch(r'[A-Za-z0-9+/=]{80,}', text):
        return True
    return False


def score_candidate_endpoint(
    url: str,
    method: str,
    data: Any,
    goal_keywords: List[str]
) -> Tuple[float, List[str], str, bool]:
    """Score candidate endpoint relevance considering both decoded URL params and response payload."""
    is_encrypted = detect_payload_encryption(data)
    unquoted_url = urllib.parse.unquote(url).lower() if url else ""
    matched_kws = []

    url_matches = 0
    for kw in goal_keywords:
        kw_clean = kw.strip().lower()
        if not kw_clean:
            continue
        if kw_clean in unquoted_url:
            url_matches += 1
            if kw_clean not in matched_kws:
                matched_kws.append(kw_clean)

    body_score, body_matched, data_path = (0.0, [], "data")
    if not is_encrypted and data is not None:
        try:
            body_score, body_matched, data_path = score_json_match(data, goal_keywords)
            for bm in body_matched:
                if bm not in matched_kws:
                    matched_kws.append(bm)
        except Exception:
            pass

    if goal_keywords:
        combined_score = max(body_score, (url_matches / len(goal_keywords)))
    else:
        combined_score = 0.0

    return min(1.0, combined_score), matched_kws, data_path, is_encrypted
