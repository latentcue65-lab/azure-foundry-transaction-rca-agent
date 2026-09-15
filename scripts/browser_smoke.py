"""Run with: uv run --with playwright python scripts/browser_smoke.py

Uses installed Microsoft Edge; no browser download is required on this Windows workspace.
The application must already be running in replay mode at http://127.0.0.1:8000.
"""

import argparse
import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--mode", choices=["replay", "foundry"], default="replay")
    args = parser.parse_args()
    timeout = 240000 if args.mode == "foundry" else 30000
    output = Path("outputs/browser") / args.mode
    output.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(channel="msedge", headless=True)
        page = browser.new_page(viewport={"width": 1365, "height": 1000})
        errors = []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.goto(args.base_url)
        expect(page.locator("#mode")).to_contain_text(
            "Offline replay" if args.mode == "replay" else "Foundry agent"
        )
        page.locator("#submit").click()
        expect(page.locator("#result")).to_be_visible(timeout=timeout)
        expect(page.locator("#status")).to_have_text("identified")
        expect(page.locator("#execution")).to_contain_text("Execution: completed")
        assert page.locator("#calls tr").count() >= 3
        expect(page.locator("#correlation")).to_contain_text("Attempt PA1")
        page.locator("#root-refs a").first.click()
        assert page.locator("#evidence-section").evaluate("element => element.open")
        page.screenshot(path=str(output / "desktop.png"), full_page=True)
        with page.expect_download() as download_info:
            page.locator("#download").click()
        download = download_info.value
        saved = output / "downloaded-report.json"
        download.save_as(str(saved))
        assert len(json.loads(saved.read_text())) == 6
        page.pdf(path=str(output / "report.pdf"), format="A4", print_background=True)
        expect(page.locator(".history-item").first).to_be_enabled(timeout=10000)
        page.locator(".history-item").first.click()
        expect(page.locator("#execution")).to_contain_text("Execution: completed")
        if args.mode == "foundry":
            page.set_viewport_size({"width": 390, "height": 844})
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.screenshot(path=str(output / "mobile.png"), full_page=True)
            assert not errors, errors
            browser.close()
            print(
                "Live Foundry browser smoke passed: actual LLM RCA, correlation, evidence links, history, JSON/PDF export and mobile layout."
            )
            return
        page.locator("#scenario").select_option("4")
        page.locator("#submit").click()
        expect(page.locator("#result")).to_be_visible(timeout=30000)
        expect(page.locator("#summary")).to_contain_text("recovered")
        page.set_viewport_size({"width": 390, "height": 844})
        assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
        page.screenshot(path=str(output / "mobile.png"), full_page=True)
        page.locator("#scenario").select_option("2")
        page.locator("#submit").click()
        expect(page.locator("#result")).to_be_visible(timeout=30000)
        expect(page.locator("#status")).to_have_text("insufficient evidence")
        page.locator("#transaction").fill("")
        page.locator("#submit").click()
        expect(page.locator("#candidates")).to_be_visible(timeout=30000)
        assert page.locator(".candidate").count() == 8
        page.locator(".candidate").filter(has_text="TX9001").click()
        expect(page.locator("#result")).to_be_visible(timeout=30000)
        expect(page.locator("#title")).to_have_text("C1001 / TX9001")
        page.locator("#transaction").fill("TX9999")
        page.locator("#submit").click()
        expect(page.locator("#error")).to_contain_text("No authorized transaction", timeout=30000)
        assert not errors, errors
        browser.close()
    print(
        "Browser smoke passed: RCA, recovery, uncertainty, discovery, scope error, history, evidence navigation, JSON/PDF export, mobile layout; no JavaScript errors."
    )


if __name__ == "__main__":
    main()
