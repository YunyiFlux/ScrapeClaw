# -*- coding: utf-8 -*-
"""Captcha and Turnstile Solvers (Auto-click and Human-In-The-Loop)."""
import asyncio
import logging
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, Any, Callable

from scrapeclaw.probe.captcha_detector import CaptchaDetector, CaptchaChallenge, ChallengeType

logger = logging.getLogger("ScrapeClawCaptcha")


class BaseCaptchaSolver(ABC):
    """Abstract base class for captcha solvers."""

    @abstractmethod
    async def solve(self, page: Any, challenge: CaptchaChallenge) -> bool:
        """Attempt to solve or bypass the challenge. Return True if resolved."""
        pass


class AutoClickTurnstileSolver(BaseCaptchaSolver):
    """Automatic click solver for simple Cloudflare Turnstile checkbox challenges."""

    def __init__(self, wait_after_click_seconds: float = 4.0):
        self.wait_after_click_seconds = wait_after_click_seconds
        self.detector = CaptchaDetector()

    async def solve(self, page: Any, challenge: CaptchaChallenge) -> bool:
        if challenge.challenge_type != ChallengeType.CLOUDFLARE_TURNSTILE:
            return False

        logger.info("Attempting automatic click bypass on Cloudflare Turnstile...")
        try:
            # First check if already resolved
            if await CaptchaDetector.is_turnstile_resolved(page):
                return True

            clicked = False
            # 1. Search all frames matching challenges.cloudflare.com or turnstile
            for frame in page.frames:
                url = frame.url
                if "challenges.cloudflare.com" in url or "turnstile" in url:
                    # Check if error code 400070 (disabled sitekey) is inside frame
                    try:
                        f_html = await frame.content()
                        if "400070" in f_html or "sitekey is disabled" in f_html:
                            logger.error("Cloudflare Turnstile sitekey is disabled by owner (error 400070). Challenge cannot be solved.")
                            return False
                    except Exception:
                        pass

                    # Try finding checkbox inside frame
                    for sel in ['input[type="checkbox"]', '.ctp-checkbox-label', '#challenge-stage', 'label', 'span.mark']:
                        loc = frame.locator(sel)
                        if await loc.count() > 0:
                            try:
                                await loc.first.click(timeout=2000)
                                logger.info(f"Clicked Turnstile element '{sel}' inside frame.")
                                clicked = True
                                break
                            except Exception:
                                pass

                    # If not clicked inside frame, try clicking bounding box of frame_element
                    if not clicked:
                        try:
                            el = await frame.frame_element()
                            box = await el.bounding_box()
                            if box and box["width"] > 20 and box["height"] > 20:
                                click_x = box["x"] + 30
                                click_y = box["y"] + box["height"] / 2
                                await page.mouse.click(click_x, click_y)
                                logger.info(f"Clicked Turnstile frame coordinate ({click_x:.1f}, {click_y:.1f}).")
                                clicked = True
                                break
                        except Exception:
                            pass

            if not clicked and hasattr(page, "frame_locator"):
                # Try frame_locator
                try:
                    frame_loc = page.frame_locator('iframe[src*="challenges.cloudflare.com"], iframe')
                    checkbox = frame_loc.locator('input[type="checkbox"], .ctp-checkbox-label, #challenge-stage')
                    if await checkbox.count() > 0:
                        await checkbox.first.click(timeout=3000)
                        logger.info("Clicked Turnstile checkbox element via frame_locator.")
                        clicked = True
                except Exception:
                    pass

            if not clicked:
                # Fallback: Try locator for any iframe matching challenges
                try:
                    iframe_el = page.locator('iframe[src*="challenges.cloudflare.com"], iframe[id*="cf-chl-widget"]')
                    if await iframe_el.count() > 0:
                        box = await iframe_el.first.bounding_box()
                        if box and box["width"] > 20 and box["height"] > 20:
                            await page.mouse.click(box["x"] + 30, box["y"] + box["height"] / 2)
                            logger.info("Clicked Turnstile iframe coordinate fallback.")
                            clicked = True
                except Exception:
                    pass

            # 2. Poll for token resolution or challenge clear
            poll_interval = 0.5
            max_wait = max(self.wait_after_click_seconds, 4.0)
            waited = 0.0
            while waited < max_wait:
                await asyncio.sleep(poll_interval)
                waited += poll_interval
                
                if await CaptchaDetector.is_turnstile_resolved(page):
                    logger.info(f"Cloudflare Turnstile token obtained automatically after {waited:.1f}s!")
                    return True

            remaining = await self.detector.detect_page(page)
            if remaining is None:
                logger.info("Cloudflare Turnstile cleared automatically!")
                return True
        except Exception as e:
            logger.debug(f"Auto-click Turnstile attempt encountered: {e}")

        return False


class HumanInTheLoopSolver(BaseCaptchaSolver):
    """Interactive human-in-the-loop solver for sliders and complex challenges."""

    def __init__(
        self,
        timeout_seconds: int = 60,
        poll_interval_seconds: float = 1.5,
        screenshot_dir: Optional[Path] = None,
        on_challenge_detected: Optional[Callable[[CaptchaChallenge, str], None]] = None,
    ):
        self.timeout_seconds = timeout_seconds
        self.poll_interval_seconds = poll_interval_seconds
        self.screenshot_dir = screenshot_dir or Path("./scrapeclaw_workspace")
        self.on_challenge_detected = on_challenge_detected
        self.detector = CaptchaDetector()

    async def solve(self, page: Any, challenge: CaptchaChallenge) -> bool:
        self.screenshot_dir.mkdir(parents=True, exist_ok=True)
        screenshot_path = self.screenshot_dir / "captcha_challenge.png"

        try:
            await page.screenshot(path=str(screenshot_path))
            logger.warning(f"Saved captcha challenge screenshot to {screenshot_path}")
        except Exception as e:
            logger.debug(f"Could not capture screenshot: {e}")

        if self.on_challenge_detected:
            try:
                self.on_challenge_detected(challenge, str(screenshot_path))
            except Exception:
                pass

        logger.warning(
            f"Human assistance requested for {challenge.challenge_type.value}: {challenge.details}. "
            f"Waiting up to {self.timeout_seconds}s for resolution..."
        )

        # Poll until challenge clears or timeout
        elapsed = 0.0
        while elapsed < self.timeout_seconds:
            await asyncio.sleep(self.poll_interval_seconds)
            elapsed += self.poll_interval_seconds

            try:
                if await CaptchaDetector.is_turnstile_resolved(page):
                    logger.info(f"Turnstile challenge token detected after {elapsed:.1f}s!")
                    return True
                remaining = await self.detector.detect_page(page)
                if remaining is None:
                    logger.info(f"Captcha challenge resolved after {elapsed:.1f}s!")
                    return True
            except Exception:
                # If page is navigating or closed, treat as resolving or continuing
                pass

        logger.error(f"Captcha challenge timed out after {self.timeout_seconds}s.")
        return False


class CaptchaBypassBridge:
    """Coordinates detection and bypass between automatic and human-in-the-loop solvers."""

    def __init__(
        self,
        auto_solve: bool = True,
        hitl_timeout_seconds: int = 60,
        screenshot_dir: Optional[Path] = None,
        on_challenge_detected: Optional[Callable[[CaptchaChallenge, str], None]] = None,
    ):
        self.auto_solve = auto_solve
        self.detector = CaptchaDetector()
        self.auto_solver = AutoClickTurnstileSolver()
        self.hitl_solver = HumanInTheLoopSolver(
            timeout_seconds=hitl_timeout_seconds,
            screenshot_dir=screenshot_dir,
            on_challenge_detected=on_challenge_detected,
        )

    async def detect_and_bypass(self, page: Any) -> Optional[CaptchaChallenge]:
        """Detect and attempt to bypass any challenge. Return resolved challenge or None."""
        challenge = await self.detector.detect_page(page)
        if not challenge:
            return None

        logger.warning(f"Detected challenge: {challenge.challenge_type.value} - {challenge.details}")

        if not self.auto_solve:
            return challenge

        # Step 1: Try auto-click solver if Turnstile
        if challenge.challenge_type == ChallengeType.CLOUDFLARE_TURNSTILE:
            solved = await self.auto_solver.solve(page, challenge)
            if solved:
                return challenge

        # Step 2: Fallback to HITL solver
        solved = await self.hitl_solver.solve(page, challenge)
        if solved:
            return challenge

        logger.warning(f"Captcha challenge {challenge.challenge_type.value} could not be resolved.")
        return None
