"""Offline smoke test for playwright_interactions.py.

Run:
    python playwright_interactions_smoke.py
"""

from playwright.sync_api import sync_playwright

from playwright_interactions import human_mouse_move_and_click, human_typing


HTML = """
<!doctype html>
<html lang="en">
  <body>
    <label for="caption">Caption</label>
    <input id="caption" type="text" />
    <button id="publish" onclick="document.body.dataset.clicked='yes'">Publish</button>
  </body>
</html>
"""


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            page = browser.new_page(viewport={"width": 1280, "height": 720})
            page.set_content(HTML, wait_until="domcontentloaded")

            expected = "Playwright smoke: Türkçe + punctuation!"
            human_typing(page, "#caption", expected)
            human_mouse_move_and_click(page, "#publish")

            assert page.locator("#caption").input_value() == expected
            assert page.locator("body").get_attribute("data-clicked") == "yes"
            print("playwright interaction smoke: PASS")
        finally:
            browser.close()


if __name__ == "__main__":
    main()
