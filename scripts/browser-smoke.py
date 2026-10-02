"""Smoke test della UI su un'istanza di prova isolata, non sui dati dell'utente.

Dipendenza di sviluppo: playwright con Chromium installato.
Il comando avvia temporaneamente il server sulla porta 8187 e lo chiude al termine.
"""

import asyncio
import os
import secrets
import subprocess
import sys
import tempfile
from pathlib import Path

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parent.parent
URL = "http://127.0.0.1:8187"


async def heartbeat():
    while True:
        await asyncio.sleep(.01)


async def check():
    password = secrets.token_urlsafe(24)
    errors = []
    beat = asyncio.create_task(heartbeat())
    with tempfile.TemporaryDirectory(prefix="figurae-browser-") as directory:
        process = subprocess.Popen(
            [sys.executable, "run.py", "--port", "8187", "--data-dir", directory],
            cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(
                    headless=True, args=["--no-sandbox", "--disable-dev-shm-usage"])
                context = await browser.new_context(viewport={"width": 1440, "height": 1000}, accept_downloads=True)
                page = await context.new_page()
                page.on("pageerror", lambda error: errors.append(str(error)))
                page.on("console", lambda message: errors.append(message.text) if message.type == "error" else None)
                for attempt in range(30):
                    try:
                        await page.goto(URL, wait_until="networkidle")
                        break
                    except Exception:
                        if attempt == 29:
                            raise
                        await asyncio.sleep(.2)
                await page.locator("#password").fill(password)
                await page.locator("#password-confirm").fill(password)
                await page.locator("#auth-form button[type=submit]").click()
                await page.get_by_role("heading", name="Tutto il progetto, in un posto.").wait_for(timeout=10000)
                await page.screenshot(path=str(ROOT.parent / "figurae-console-preview.png"), full_page=True)
                route_titles = {"token": "Figurae token", "blockchain": "Esploratore BlackChain", "sales": "Gestione vendite", "whitepaper": "White paper", "settings": "Impostazioni del progetto", "overview": "Tutto il progetto, in un posto."}
                for route in route_titles:
                    await page.locator(f'aside a[href="#{route}"]').click()
                    await page.get_by_role('heading', name=route_titles[route], exact=True).wait_for()
                    print("Vista:", route, "OK", flush=True)
                await page.locator("[data-action=add-price]").first.click()
                await page.locator("[name=price_eur]").fill("0.00001")
                await page.locator("[name=source]").fill("Rilevazione di test locale")
                await page.locator("#price-form button[type=submit]").click()
                await page.locator("svg.price-chart").wait_for()
                await page.locator("[data-action=new-sale]").click()
                await page.locator("[name=customer]").fill("Cliente demo (test)")
                await page.locator("[name=wallet_address]").fill("0x1111111111111111111111111111111111111111")
                await page.locator("[name=quantity]").fill("123.000000000000000001")
                await page.locator("[name=unit_price_eur]").fill("0.00001")
                await page.locator("#sale-form button[type=submit]").click()
                await page.locator('aside a[href="#sales"]').click()
                await page.get_by_text("Cliente demo (test)", exact=True).wait_for()
                quantity_cell = page.locator('#sales-table tbody tr').first.locator('td').nth(1)
                await quantity_cell.wait_for()
                assert (await quantity_cell.inner_text()).strip() == "123,000000000000000001 FIG", await quantity_cell.inner_text()
                await page.locator("[data-action=sale-paid]").click()
                await page.locator("[name=payment_reference]").fill("Ricevuta di test locale")
                await page.locator("#paid-form button[type=submit]").click()
                await page.locator('#sales-table .status-paid').wait_for()
                await page.locator('aside a[href="#blockchain"]').click()
                await page.locator("[data-action=new-transaction]").click()
                await page.locator("#tx-sender").select_option("carol")
                await page.locator("#tx-kind").select_option("stake")
                await page.locator("#tx-amount").fill("5")
                await page.locator("#transaction-form button[type=submit]").click()
                await page.get_by_text("nonce 4", exact=True).wait_for()
                await page.locator("[data-action=forge]").click()
                await page.get_by_text("#5", exact=True).first.wait_for()
                await page.locator('aside a[href="#whitepaper"]').click()
                await page.locator("#paper-mission").fill("Figurae: progetto gestito dalla console locale. Test browser.")
                await page.locator("#whitepaper-form button[type=submit]").click()
                await page.get_by_text("Versione 2", exact=True).wait_for()
                async with page.expect_download() as capture:
                    await page.locator("[data-action=whitepaper-md]").click()
                document = Path(await (await capture.value).path()).read_text()
                assert "100.000.000.000" in document and "Test browser." in document
                await page.reload(wait_until="networkidle")
                await page.locator("#paper-mission").wait_for()
                assert "Test browser." in await page.locator("#paper-mission").input_value()
                await page.locator('aside a[href="#overview"]').click()
                await page.get_by_role('heading', name='Tutto il progetto, in un posto.', exact=True).wait_for()
                await page.set_viewport_size({"width": 390, "height": 844})
                await page.wait_for_timeout(150)
                await page.screenshot(path=str(ROOT.parent / "figurae-console-mobile.png"), full_page=True)
                assert not await page.evaluate("document.documentElement.scrollWidth > window.innerWidth"), "Mobile overflow"
                assert not errors, errors
                print("Browser: navigazione, prezzi, vendite, pagamento, stake/blocco, white paper, download, persistenza e mobile OK", flush=True)
                await browser.close()
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
            beat.cancel()


if __name__ == "__main__":
    asyncio.run(check())
