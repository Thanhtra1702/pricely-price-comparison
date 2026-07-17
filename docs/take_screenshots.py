"""Capture current PriceLy marketplace and popup-chat screenshots for the README."""

from playwright.sync_api import sync_playwright


SCREENSHOTS = [
    {"name": "deals-explorer", "actions": []},
    {"name": "chatbot-overlay", "actions": ["open_chat"]},
    {"name": "chatbot-overlay-with-results", "actions": ["open_chat", "send_chat"]},
]
BASE_URL = "http://localhost:3000/deals"
OUTPUT_DIR = "docs/images"
VIEWPORT = {"width": 1440, "height": 900}


def apply_actions(page, actions: list[str]) -> None:
    for action in actions:
        if action == "open_chat":
            page.get_by_role("button", name="Mở AI Assistant").click()
            page.wait_for_timeout(400)
        elif action == "send_chat":
            composer = page.get_by_placeholder("Nhập tên sản phẩm cần tìm giá tốt nhất...")
            composer.fill("So sánh giá sữa Vinamilk 1L")
            composer.press("Enter")
            page.wait_for_timeout(5000)


def main() -> None:
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        for shot in SCREENSHOTS:
            context = browser.new_context(viewport=VIEWPORT, device_scale_factor=2)
            page = context.new_page()
            page.goto(BASE_URL, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(3000)
            apply_actions(page, shot["actions"])
            page.screenshot(path=f"{OUTPUT_DIR}/{shot['name']}.png", full_page=False)
            context.close()
        browser.close()


if __name__ == "__main__":
    main()
