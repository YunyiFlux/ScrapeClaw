# -*- coding: utf-8 -*-
"""Captcha, Turnstile, and Anti-Bot Challenge Detector."""
import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Any, Dict


class ChallengeType(str, Enum):
    NONE = "none"
    CLOUDFLARE_TURNSTILE = "cloudflare_turnstile"
    GEETEST_SLIDER = "geetest_slider"
    RECAPTCHA = "recaptcha"
    HCAPTCHA = "hcaptcha"
    TENCENT_CAPTCHA = "tencent_captcha"
    GENERIC_BLOCK = "generic_block"


@dataclass
class CaptchaChallenge:
    challenge_type: ChallengeType
    title: str
    target_selector: str
    details: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "challenge_type": self.challenge_type.value,
            "title": self.title,
            "target_selector": self.target_selector,
            "details": self.details,
        }


class CaptchaDetector:
    """Detects bot challenges and captchas from HTML content or live Playwright page."""

    # Rules mapping: (ChallengeType, pattern_list, preferred_selector, description)
    RULES = [
        (
            ChallengeType.CLOUDFLARE_TURNSTILE,
            [
                r"challenges\.cloudflare\.com",
                r"cf-turnstile",
                r"Just a moment\.\.\.",
                r"_cf_chl_opt",
                r"turnstile-wrapper",
            ],
            'iframe[src*="challenges.cloudflare.com"], .cf-turnstile',
            "Cloudflare Turnstile or Managed Challenge detected",
        ),
        (
            ChallengeType.GEETEST_SLIDER,
            [
                r"geetest",
                r"gt_slider",
                r"geetest_holder",
                r"geetest_radar_tip",
            ],
            ".geetest_holder, .geetest_radar_tip, .geetest_slider",
            "Geetest slide/click captcha detected",
        ),
        (
            ChallengeType.RECAPTCHA,
            [
                r"google\.com/recaptcha",
                r"g-recaptcha",
                r"recaptcha/api\.js",
            ],
            'iframe[src*="google.com/recaptcha"], .g-recaptcha',
            "Google reCAPTCHA challenge detected",
        ),
        (
            ChallengeType.HCAPTCHA,
            [
                r"hcaptcha\.com",
                r"h-captcha",
            ],
            'iframe[src*="hcaptcha.com"], .h-captcha',
            "hCaptcha challenge detected",
        ),
        (
            ChallengeType.TENCENT_CAPTCHA,
            [
                r"captcha\.gtimg\.com",
                r"TencentCaptcha",
                r"turing\.captcha",
            ],
            "#TCaptcha, .tcaptcha-transform",
            "Tencent security captcha detected",
        ),
        (
            ChallengeType.GENERIC_BLOCK,
            [
                r"安全验证",
                r"请完成安全验证",
                r"滑动验证",
                r"Security Check",
                r"Access Denied",
                r"Attention Required! \| Cloudflare",
                r"Verify you are human",
                r"Robot or Human",
            ],
            "body",
            "Generic anti-bot security barrier page detected",
        ),
    ]

    def detect_html(self, html: str, title: str = "") -> Optional[CaptchaChallenge]:
        """Detect captcha in static HTML or page title."""
        combined = f"{title}\n{html}"

        for challenge_type, patterns, selector, desc in self.RULES:
            for pat in patterns:
                if re.search(pat, combined, re.IGNORECASE):
                    return CaptchaChallenge(
                        challenge_type=challenge_type,
                        title=title,
                        target_selector=selector,
                        details=desc,
                    )
        return None

    @staticmethod
    async def is_turnstile_resolved(page: Any) -> bool:
        """Check if Turnstile response token has been populated or cf_clearance set."""
        try:
            evaluate_fn = getattr(page, "evaluate", None)
            if evaluate_fn and callable(evaluate_fn):
                res = await page.evaluate("""
                () => {
                    const els = document.querySelectorAll('input[name="cf-turnstile-response"], [name*="turnstile-response"], [id*="response"]');
                    for (const el of els) {
                        if (el && el.value && el.value.trim().length > 5) {
                            return true;
                        }
                    }
                    return false;
                }
                """)
                if isinstance(res, bool) and res is True:
                    return True
        except Exception:
            pass

        try:
            context = getattr(page, "context", None)
            if context and hasattr(context, "cookies") and callable(context.cookies):
                cookies = await context.cookies()
                if isinstance(cookies, list):
                    for c in cookies:
                        if isinstance(c, dict) and c.get("name") == "cf_clearance" and len(c.get("value", "")) > 5:
                            return True
        except Exception:
            pass

        return False

    async def detect_page(self, page: Any) -> Optional[CaptchaChallenge]:
        """Detect captcha on active Playwright Page object."""
        # If Turnstile token is already present, it is already verified
        if await self.is_turnstile_resolved(page):
            return None

        title = ""
        try:
            title = await page.title()
        except Exception:
            pass

        # 1. First inspect title and DOM content
        try:
            content = await page.content()
            challenge = self.detect_html(content, title=title)
            if challenge:
                return challenge
        except Exception:
            pass

        # 2. Inspect active iframes for cross-domain challenge embeds
        try:
            frames = page.frames
            for f in frames:
                url = f.url
                if "challenges.cloudflare.com" in url:
                    return CaptchaChallenge(
                        challenge_type=ChallengeType.CLOUDFLARE_TURNSTILE,
                        title=title,
                        target_selector='iframe[src*="challenges.cloudflare.com"]',
                        details="Cloudflare Turnstile iframe found in frame tree",
                    )
                if "recaptcha" in url:
                    return CaptchaChallenge(
                        challenge_type=ChallengeType.RECAPTCHA,
                        title=title,
                        target_selector='iframe[src*="google.com/recaptcha"]',
                        details="Google reCAPTCHA iframe found in frame tree",
                    )
                if "hcaptcha.com" in url:
                    return CaptchaChallenge(
                        challenge_type=ChallengeType.HCAPTCHA,
                        title=title,
                        target_selector='iframe[src*="hcaptcha.com"]',
                        details="hCaptcha iframe found in frame tree",
                    )
        except Exception:
            pass

        return None
