from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import yaml
from playwright.async_api import Locator, Page, TimeoutError as PlaywrightTimeoutError, async_playwright


@dataclass(frozen=True)
class Config:
    raw: dict[str, Any]
    path: Path

    @property
    def target_url(self) -> str:
        return str(self.raw["target"]["url"])

    @property
    def sale_time(self) -> datetime | None:
        value = self.raw.get("target", {}).get("sale_time")
        if not value:
            return None
        tz = ZoneInfo(str(self.raw.get("target", {}).get("timezone", "Asia/Shanghai")))
        return datetime.strptime(str(value), "%Y-%m-%d %H:%M:%S").replace(tzinfo=tz)

    @property
    def browser(self) -> dict[str, Any]:
        return self.raw.get("browser", {})

    @property
    def behavior(self) -> dict[str, Any]:
        return self.raw.get("behavior", {})

    @property
    def selectors(self) -> dict[str, str]:
        return {k: str(v or "") for k, v in self.raw.get("selectors", {}).items()}

    @property
    def purchase(self) -> dict[str, Any]:
        return self.raw.get("purchase", {})

    @property
    def notifications(self) -> dict[str, Any]:
        return self.raw.get("notifications", {})


def load_config(path: Path) -> Config:
    with path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)
    if not isinstance(raw, dict):
        raise ValueError("Config file must contain a YAML object.")
    if not raw.get("target", {}).get("url"):
        raise ValueError("target.url is required.")
    return Config(raw=raw, path=path)


async def wait_until_sale_time(config: Config) -> None:
    sale_time = config.sale_time
    if sale_time is None:
        return

    while True:
        now = datetime.now(sale_time.tzinfo)
        seconds = (sale_time - now).total_seconds()
        if seconds <= 0:
            return
        nap = min(seconds, 30)
        print(f"Waiting for sale time: {sale_time.isoformat()} ({seconds:.0f}s left)")
        await asyncio.sleep(nap)


async def first_visible(page: Page, selector: str, timeout_ms: int = 250) -> Locator | None:
    if not selector:
        return None
    locator = page.locator(selector).first
    try:
        await locator.wait_for(state="visible", timeout=timeout_ms)
        return locator
    except PlaywrightTimeoutError:
        return None


async def click_if_configured(page: Page, selector: str, label: str) -> bool:
    locator = await first_visible(page, selector, timeout_ms=600)
    if locator is None:
        return False
    await locator.click()
    print(f"Selected {label}.")
    return True


async def prepare_options(page: Page, config: Config) -> None:
    selectors = config.selectors
    await click_if_configured(page, selectors.get("date_option", ""), "date")
    await click_if_configured(page, selectors.get("price_option", ""), "price")

    quantity = int(config.purchase.get("quantity", 1))
    increase_selector = selectors.get("quantity_increase_button", "")
    for _ in range(max(0, quantity - 1)):
        clicked = await click_if_configured(page, increase_selector, "quantity")
        if not clicked:
            break


async def detect_status(page: Page, config: Config) -> str:
    selectors = config.selectors
    if await first_visible(page, selectors.get("login_required_text", "")):
        return "login_required"
    if await first_visible(page, selectors.get("available_button", "")):
        return "available"
    if await first_visible(page, selectors.get("sold_out_text", "")):
        return "sold_out"
    return "unknown"


async def notify_success(config: Config) -> None:
    if config.notifications.get("terminal_bell", True):
        sys.stdout.write("\a")
        sys.stdout.flush()
    print(config.notifications.get("success_message", "Ticket appears available. Please confirm manually."))


async def run(config: Config, login_only: bool) -> None:
    async with async_playwright() as pw:
        browser_config = config.browser
        user_data_dir = str(config.path.parent / browser_config.get("user_data_dir", ".browser-profile"))
        context = await pw.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=bool(browser_config.get("headless", False)),
            slow_mo=int(browser_config.get("slow_mo_ms", 0)),
        )
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(config.target_url, wait_until="domcontentloaded")

        if login_only:
            print("Login-only mode: finish login in the browser, then press Enter here.")
            await asyncio.to_thread(input)
            await context.close()
            return

        await wait_until_sale_time(config)
        refresh_interval = float(config.behavior.get("refresh_interval_seconds", 1.2))
        max_refresh_interval = float(config.behavior.get("max_refresh_interval_seconds", 5))
        max_attempts = int(config.behavior.get("max_attempts", 300))

        for attempt in range(1, max_attempts + 1):
            print(f"Attempt {attempt}/{max_attempts}")
            await page.reload(wait_until="domcontentloaded")
            await prepare_options(page, config)

            status = await detect_status(page, config)
            print(f"Status: {status}")

            if status == "login_required":
                print("Login appears required. Please finish login in the browser, then press Enter here.")
                await asyncio.to_thread(input)
                continue

            if status == "available":
                await notify_success(config)
                buy_button = await first_visible(page, config.selectors.get("available_button", ""), timeout_ms=1500)
                if buy_button is not None:
                    await buy_button.click()

                await prepare_options(page, config)
                submit_selector = config.selectors.get("submit_order_button", "")
                if not config.behavior.get("stop_before_payment", True) and submit_selector:
                    submit = await first_visible(page, submit_selector, timeout_ms=1500)
                    if submit is not None:
                        await submit.click()
                else:
                    print("Stopped before payment/order finalization for manual review.")

                if config.behavior.get("screenshot_on_success", True):
                    screenshot = config.path.parent / "success.png"
                    await page.screenshot(path=str(screenshot), full_page=True)
                    print(f"Saved screenshot: {screenshot}")
                await asyncio.to_thread(input, "Press Enter to close browser...")
                break

            await asyncio.sleep(min(refresh_interval, max_refresh_interval))

        await context.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Personal-use ticket availability helper.")
    parser.add_argument("-c", "--config", default="config.yaml", help="Path to YAML config.")
    parser.add_argument("--login-only", action="store_true", help="Open the page for manual login and save cookies.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config_path = Path(args.config).expanduser().resolve()
    config = load_config(config_path)
    asyncio.run(run(config, login_only=args.login_only))


if __name__ == "__main__":
    main()
