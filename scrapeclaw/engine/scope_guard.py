"""Target Scope Guard - Domain Lock for Navigation and Probing."""
from urllib.parse import urlparse
from typing import List, Set, Tuple, Optional

def extract_root_domain(url_or_host: str) -> str:
    """Extract normalized root domain (e.g. s.baidu.com -> baidu.com, 127.0.0.1 -> 127.0.0.1)."""
    if not url_or_host:
        return ""
    host = urlparse(url_or_host).netloc if "://" in url_or_host else url_or_host
    host = host.split(":")[0].strip().lower()
    
    if host.replace(".", "").isdigit() or host == "localhost":
        return host
        
    parts = host.split(".")
    if len(parts) >= 2:
        if len(parts) >= 3 and parts[-2] in ("com", "edu", "gov", "org", "net"):
            return ".".join(parts[-3:])
        return ".".join(parts[-2:])
    return host

class TargetScopeGuard:
    def __init__(self, target_url: str, allow_cross_domain: bool = False, extra_allowed: Optional[List[str]] = None):
        self.target_url = target_url
        self.allow_cross_domain = allow_cross_domain
        self.root_domain = extract_root_domain(target_url)
        self.allowed_domains: Set[str] = {self.root_domain}
        if extra_allowed:
            for d in extra_allowed:
                self.allowed_domains.add(extract_root_domain(d))

    def is_in_scope(self, dest_url: str) -> bool:
        if self.allow_cross_domain:
            return True
        dest_root = extract_root_domain(dest_url)
        return dest_root in self.allowed_domains

    def check_navigation(self, dest_url: str) -> Tuple[bool, str]:
        if self.is_in_scope(dest_url):
            return True, ""
        return False, (
            f"Scope Violation: Navigation to '{dest_url}' is blocked by TargetScopeGuard. "
            f"You are strictly restricted to the target domain (*.{self.root_domain}). "
            f"Extract the best available fields from the target, or synthesize a partial crawler."
        )
