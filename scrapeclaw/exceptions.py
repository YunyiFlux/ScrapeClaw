class ScrapeClawError(Exception):
    """Base exception for all ScrapeClaw errors."""
    pass


class ConfigurationError(ScrapeClawError):
    """Raised when configuration, API keys, or settings are missing or invalid."""
    pass


class BrowserLaunchError(ScrapeClawError):
    """Raised when Playwright browser failed to launch or install."""
    pass


class TargetNavigationError(ScrapeClawError):
    """Raised when navigating to target URL fails (DNS, 404, timeout)."""
    pass


class ReverseEngineeringError(ScrapeClawError):
    """Raised when reverse engineering fails to find endpoints or exceeds max steps."""
    pass


class ExecutionGateError(ScrapeClawError):
    """Raised when synthesized crawler fails physical sandbox verification."""
    pass
