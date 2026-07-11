"""Reliable Playwright interaction helpers for visible, user-assisted flows.

These helpers intentionally avoid browser fingerprint spoofing and automation-flag
hiding. They are designed for ordinary UI testing and user-assisted publishing.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass

from playwright.sync_api import Page, TimeoutError as PlaywrightTimeoutError


@dataclass(frozen=True)
class InteractionTiming:
    min_key_delay_ms: int = 40
    max_key_delay_ms: int = 150
    pause_probability: float = 0.05
    min_pause_seconds: float = 0.3
    max_pause_seconds: float = 0.8

    def __post_init__(self) -> None:
        if self.min_key_delay_ms < 0:
            raise ValueError("min_key_delay_ms must be non-negative")
        if self.max_key_delay_ms < self.min_key_delay_ms:
            raise ValueError("max_key_delay_ms must be >= min_key_delay_ms")
        if not 0.0 <= self.pause_probability <= 1.0:
            raise ValueError("pause_probability must be between 0 and 1")


def human_typing(
    page: Page,
    selector: str,
    text: str,
    *,
    timing: InteractionTiming | None = None,
    timeout_ms: int = 10_000,
) -> None:
    """Click an editable element and enter text with small randomized delays.

    ``keyboard.insert_text`` is used instead of ``keyboard.press`` because press
    interprets characters such as ``+`` and uppercase letters as key names.
    """

    timing = timing or InteractionTiming()
    locator = page.locator(selector).first
    locator.wait_for(state="visible", timeout=timeout_ms)
    locator.click(timeout=timeout_ms)

    for char in text:
        page.keyboard.insert_text(char)
        time.sleep(
            random.randint(timing.min_key_delay_ms, timing.max_key_delay_ms) / 1000
        )
        if random.random() < timing.pause_probability:
            time.sleep(
                random.uniform(
                    timing.min_pause_seconds,
                    timing.max_pause_seconds,
                )
            )


def human_mouse_move_and_click(
    page: Page,
    selector: str,
    *,
    timeout_ms: int = 10_000,
) -> None:
    """Move to a random point inside a visible element and click it."""

    locator = page.locator(selector).first
    locator.wait_for(state="visible", timeout=timeout_ms)
    locator.scroll_into_view_if_needed(timeout=timeout_ms)
    box = locator.bounding_box(timeout=timeout_ms)

    if box is None:
        locator.click(timeout=timeout_ms)
        return

    target_x = box["x"] + box["width"] * random.uniform(0.3, 0.7)
    target_y = box["y"] + box["height"] * random.uniform(0.3, 0.7)
    page.mouse.move(target_x, target_y, steps=random.randint(8, 20))
    time.sleep(random.uniform(0.05, 0.2))
    page.mouse.click(target_x, target_y, delay=random.randint(50, 180))


def wait_for_user_assisted_page(
    page: Page,
    url: str,
    *,
    timeout_ms: int = 60_000,
) -> None:
    """Open a page and wait for DOM readiness without brittle network-idle waits."""

    try:
        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    except PlaywrightTimeoutError as exc:
        raise RuntimeError(f"Page did not become ready within {timeout_ms} ms: {url}") from exc
