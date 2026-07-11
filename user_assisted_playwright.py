"""Visible Playwright runner for authorized, user-assisted UI testing.

This module uses normal browser settings. It does not spoof fingerprints, hide
Playwright, bypass CAPTCHA, or suppress platform controls.
"""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from typing import Optional

from playwright.sync_api import sync_playwright

from playwright_interactions import wait_for_user_assisted_page
from utils.antibot_resilience import human_mouse_move_and_click, human_typing
from utils.network_identity import apply_test_page_defaults, build_context_options

DEFAULT_URL = "https://www.tiktok.com/creator-center/upload"


def run_assisted_session(
    *,
    url: str = DEFAULT_URL,
    text_selector: Optional[str] = None,
    text: Optional[str] = None,
    click_selector: Optional[str] = None,
    headless: bool = False,
    wait_for_enter: bool = True,
) -> None:
    """Open an authorized test page and optionally perform explicit UI actions."""

    if bool(text_selector) != (text is not None):
        raise ValueError("text_selector and text must be supplied together")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=headless)
        context = browser.new_context(
            **build_context_options(width=1280, height=720)
        )
        page = context.new_page()
        apply_test_page_defaults(page, timeout_ms=20_000)

        try:
            print(f"Hedefe gidiliyor: {url}")
            wait_for_user_assisted_page(page, url, timeout_ms=60_000)

            if text_selector is not None and text is not None:
                human_typing(page, text_selector, text)
            if click_selector is not None:
                human_mouse_move_and_click(page, click_selector)

            print("Sayfa hazır. Giriş veya doğrulama gerekiyorsa tarayıcıda tamamlayın.")
            if wait_for_enter:
                input("Tarayıcıyı kapatmak için Enter'a basın: ")
        finally:
            context.close()
            browser.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Yetkili, kullanıcı destekli Playwright UI testi"
    )
    parser.add_argument("--url", default=DEFAULT_URL)
    parser.add_argument("--text-selector")
    parser.add_argument("--text")
    parser.add_argument("--click-selector")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Sayfa hazır olduğunda Enter beklemeden tarayıcıyı kapat",
    )
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        run_assisted_session(
            url=args.url,
            text_selector=args.text_selector,
            text=args.text,
            click_selector=args.click_selector,
            headless=args.headless,
            wait_for_enter=not args.no_wait,
        )
    except (RuntimeError, ValueError) as exc:
        print(f"Test başlatılamadı: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
