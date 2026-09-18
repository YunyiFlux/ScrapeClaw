# -*- coding: utf-8 -*-
"""ScrapeClaw probe subpackage."""
from scrapeclaw.probe.browser import BrowserProbe
from scrapeclaw.probe.session_manager import (
    SessionBundle,
    CookieItem,
    load_session_bundle,
    save_session_bundle,
)
from scrapeclaw.probe.captcha_detector import (
    CaptchaDetector,
    CaptchaChallenge,
    ChallengeType,
)
from scrapeclaw.probe.captcha_solvers import (
    BaseCaptchaSolver,
    AutoClickTurnstileSolver,
    HumanInTheLoopSolver,
    CaptchaBypassBridge,
)

__all__ = [
    "BrowserProbe",
    "SessionBundle",
    "CookieItem",
    "load_session_bundle",
    "save_session_bundle",
    "CaptchaDetector",
    "CaptchaChallenge",
    "ChallengeType",
    "BaseCaptchaSolver",
    "AutoClickTurnstileSolver",
    "HumanInTheLoopSolver",
    "CaptchaBypassBridge",
]
