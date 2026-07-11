"""Playwright interaction helpers for visible, user-authorized UI flows.

The helpers improve timing and pointer reliability. They do not hide automation
signals, spoof fingerprints, bypass CAPTCHA, or defeat platform controls.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import random
from typing import Any, Optional


@dataclass(frozen=True)
class InteractionConfig:
    min_key_delay_ms: int = 30
    max_key_delay_ms: int = 120
    pause_probability: float = 0.05
    min_pause_ms: int = 200
    max_pause_ms: int = 600
    min_mouse_steps: int = 15
    max_mouse_steps: int = 40
    min_pre_click_ms: int = 100
    max_pre_click_ms: int = 300
    min_hold_ms: int = 35
    max_hold_ms: int = 110
    timeout_ms: int = 10_000

    def __post_init__(self) -> None:
        ranges = (
            ("key delay", self.min_key_delay_ms, self.max_key_delay_ms),
            ("pause", self.min_pause_ms, self.max_pause_ms),
            ("mouse steps", self.min_mouse_steps, self.max_mouse_steps),
            ("pre-click", self.min_pre_click_ms, self.max_pre_click_ms),
            ("hold", self.min_hold_ms, self.max_hold_ms),
        )
        for name, low, high in ranges:
            if low < 0 or high < low:
                raise ValueError(f"invalid {name} range: {low}..{high}")
        if not 0.0 <= self.pause_probability <= 1.0:
            raise ValueError("pause_probability must be between 0 and 1")
        if self.min_mouse_steps < 1:
            raise ValueError("min_mouse_steps must be at least 1")
        if self.timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")


@dataclass
class PointerState:
    x: float = 0.0
    y: float = 0.0


def _wait(page: Any, milliseconds: int) -> None:
    if milliseconds > 0:
        page.wait_for_timeout(milliseconds)


def _randint(rng: random.Random, low: int, high: int) -> int:
    return low if low == high else rng.randint(low, high)


def human_typing_locator(
    page: Any,
    locator: Any,
    text: str,
    *,
    replace: bool = True,
    config: Optional[InteractionConfig] = None,
    rng: Optional[random.Random] = None,
) -> None:
    """Focus a resolved locator and enter Unicode text with bounded delays."""

    if not isinstance(text, str):
        raise TypeError("text must be a string")
    cfg = config or InteractionConfig()
    random_source = rng or random.Random()
    locator.wait_for(state="visible", timeout=cfg.timeout_ms)
    locator.click(timeout=cfg.timeout_ms)
    if replace:
        page.keyboard.press("Control+A")

    for char in text:
        if char == "\n":
            page.keyboard.press("Enter")
        elif char == "\t":
            page.keyboard.press("Tab")
        else:
            page.keyboard.insert_text(char)
        _wait(page, _randint(random_source, cfg.min_key_delay_ms, cfg.max_key_delay_ms))
        if random_source.random() < cfg.pause_probability:
            _wait(page, _randint(random_source, cfg.min_pause_ms, cfg.max_pause_ms))


def human_typing(
    page: Any,
    selector: str,
    text: str,
    *,
    config: Optional[InteractionConfig] = None,
    rng: Optional[random.Random] = None,
) -> None:
    human_typing_locator(
        page,
        page.locator(selector),
        text,
        config=config,
        rng=rng,
    )


def human_mouse_move_and_click(
    page: Any,
    selector: str,
    *,
    pointer: Optional[PointerState] = None,
    config: Optional[InteractionConfig] = None,
    rng: Optional[random.Random] = None,
) -> PointerState:
    """Move along a quadratic Bezier curve and click a visible locator."""

    cfg = config or InteractionConfig()
    random_source = rng or random.Random()
    state = pointer or PointerState()
    locator = page.locator(selector)
    locator.wait_for(state="visible", timeout=cfg.timeout_ms)
    box = locator.bounding_box(timeout=cfg.timeout_ms)
    if not box or box.get("width", 0) <= 0 or box.get("height", 0) <= 0:
        locator.click(timeout=cfg.timeout_ms)
        return state

    target_x = float(box["x"]) + float(box["width"]) * random_source.uniform(0.2, 0.8)
    target_y = float(box["y"]) + float(box["height"]) * random_source.uniform(0.2, 0.8)
    start_x, start_y = state.x, state.y
    distance = math.hypot(target_x - start_x, target_y - start_y)
    bend = min(max(distance * 0.18, 12.0), 120.0)
    control_x = (start_x + target_x) / 2 + random_source.uniform(-bend, bend)
    control_y = (start_y + target_y) / 2 + random_source.uniform(-bend, bend)
    steps = _randint(random_source, cfg.min_mouse_steps, cfg.max_mouse_steps)

    for index in range(1, steps + 1):
        t = index / steps
        inverse = 1.0 - t
        x = inverse * inverse * start_x + 2 * inverse * t * control_x + t * t * target_x
        y = inverse * inverse * start_y + 2 * inverse * t * control_y + t * t * target_y
        page.mouse.move(x, y)

    _wait(page, _randint(random_source, cfg.min_pre_click_ms, cfg.max_pre_click_ms))
    page.mouse.down()
    try:
        _wait(page, _randint(random_source, cfg.min_hold_ms, cfg.max_hold_ms))
    finally:
        page.mouse.up()
    state.x, state.y = target_x, target_y
    return state
