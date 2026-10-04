"""Minimal ChatGPT Web callback via an existing Chrome CDP session."""

import time

from playwright.sync_api import sync_playwright


CDP_URL = "http://127.0.0.1:9222"
READY_TIMEOUT_SECONDS = 120
COMPOSER_SELECTORS = (
    "form [contenteditable='true'][role='textbox']",
    "form [contenteditable='true']",
)
SEND_BUTTON_SELECTORS = (
    "form button[aria-label='送信']",
    "form button[type='submit']",
)
STOP_BUTTON_SELECTORS = ("form button[aria-label='停止']",)


def _visible(page, selectors):
    for selector in selectors:
        locator = page.locator(selector)
        matches = [locator.nth(i) for i in range(locator.count()) if locator.nth(i).is_visible()]
        if len(matches) == 1:
            return matches[0]
        if len(matches) > 1:
            raise RuntimeError(f"multiple visible elements: {selector}")
    return None


def notify_chatgpt(target_url: str, message: str) -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.connect_over_cdp(CDP_URL)
        pages = [
            page
            for context in browser.contexts
            for page in context.pages
            if page.url.rstrip("/") == target_url.rstrip("/")
        ]
        if len(pages) != 1:
            raise RuntimeError(f"target chat count: {len(pages)}")
        page = pages[0]
        page.bring_to_front()

        deadline = time.monotonic() + READY_TIMEOUT_SECONDS
        while _visible(page, STOP_BUTTON_SELECTORS) is not None:
            if time.monotonic() >= deadline:
                raise RuntimeError("ChatGPT ready timeout")
            page.wait_for_timeout(500)

        composer = _visible(page, COMPOSER_SELECTORS)
        if composer is None:
            raise RuntimeError("composer not found")
        if (composer.inner_text() or "").strip():
            raise RuntimeError("composer is not empty")

        composer.focus()
        page.keyboard.insert_text(message)
        send_button = _visible(page, SEND_BUTTON_SELECTORS)
        if send_button is None or not send_button.is_enabled():
            raise RuntimeError("send button unavailable")
        send_button.click()
