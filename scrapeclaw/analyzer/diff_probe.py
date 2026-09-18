"""Minimal Request-Face Differential Pruning Probe."""
import httpx
import copy
from typing import Tuple, Dict, Any

NOISE_HEADER_KEYS = {
    "sec-ch-ua", "sec-ch-ua-mobile", "sec-ch-ua-platform",
    "sec-fetch-site", "sec-fetch-mode", "sec-fetch-dest",
    "accept-encoding", "accept-language", "priority",
    "user-agent-original", "upgrade-insecure-requests"
}

async def prune_minimal_headers(
    url: str,
    method: str,
    raw_headers: dict[str, str],
    cookies: dict[str, str],
    data_payload: Any = None
) -> Tuple[dict[str, str], dict[str, str]]:
    async with httpx.AsyncClient(timeout=10.0, verify=False) as client:
        # Step 1: Baseline
        try:
            base_resp = await client.request(method, url, headers=raw_headers, cookies=cookies, json=data_payload)
            if base_resp.status_code != 200:
                return raw_headers, cookies
            base_len = len(base_resp.content)
        except Exception:
            return raw_headers, cookies

        # Step 2: Strip known browser noise
        pruned_headers = {k: v for k, v in raw_headers.items() if k.lower() not in NOISE_HEADER_KEYS}
        
        # Step 3: Progressive single-header exclusion
        candidate_keys = list(pruned_headers.keys())
        for key in candidate_keys:
            if key.lower() in ("host", "content-length"):
                pruned_headers.pop(key, None)
                continue
            
            temp_headers = copy.deepcopy(pruned_headers)
            temp_headers.pop(key, None)
            
            try:
                test_resp = await client.request(method, url, headers=temp_headers, cookies=cookies, json=data_payload)
                if test_resp.status_code == 200 and abs(len(test_resp.content) - base_len) < max(200, base_len * 0.1):
                    pruned_headers = temp_headers
            except Exception:
                pass

        # Step 4: Cookie isolation test
        pruned_cookies = copy.deepcopy(cookies)
        try:
            cookie_free_resp = await client.request(method, url, headers=pruned_headers, json=data_payload)
            if cookie_free_resp.status_code == 200 and abs(len(cookie_free_resp.content) - base_len) < max(200, base_len * 0.1):
                pruned_cookies = {}
        except Exception:
            pass

        return pruned_headers, pruned_cookies
