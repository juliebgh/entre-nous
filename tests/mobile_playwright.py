"""Test de bout en bout sur instance locale jetable. Voir QA.md."""
import asyncio
import os
from playwright.async_api import async_playwright, expect

URL = os.getenv("TEST_BASE_URL", "http://127.0.0.1:8080").rstrip("/")


async def state(page):
    return await page.evaluate("async () => (await fetch('/api/state')).json()")


async def choose(page, index):
    await page.locator(f'[data-choice="{index}"]').click()
    await page.locator("#lock").click()


async def main():
    async with async_playwright() as p:
        executable = os.getenv("CHROMIUM_PATH") or None
        browsers = await asyncio.gather(*(
            p.chromium.launch(executable_path=executable) for _ in range(2)
        ))
        try:
            contexts = await asyncio.gather(*(
                b.new_context(**p.devices[device], reduced_motion="reduce")
                for b, device in zip(browsers, ("iPhone 13", "Pixel 7"))
            ))
            a, b = await asyncio.gather(*(c.new_page() for c in contexts))
            errors = []
            for page in (a, b):
                page.on("pageerror", lambda exc: errors.append(str(exc)))
                page.set_default_timeout(8_000)
            await asyncio.gather(a.goto(URL), b.goto(URL))
            await a.locator("#create").click()
            await a.locator("#name").fill("Lou")
            await a.locator("#enter").click()
            await a.locator("#start").wait_for(state="attached")
            code = (await state(a))["code"]
            await b.locator("#join").click()
            await b.locator("#name").fill("Noa")
            await b.locator("#code").fill(code)
            await b.locator("#enter").click()
            await expect(a.locator("#start")).to_be_enabled()
            await a.locator("#start").click()
            await asyncio.gather(*(x.locator('[data-choice="0"]').wait_for() for x in (a, b)))
            left, right = await asyncio.gather(state(a), state(b))
            assert left["card"] == right["card"] and left["seat"] != right["seat"]
            for x in (a, b):
                assert await x.evaluate("document.documentElement.scrollWidth <= innerWidth")
            await asyncio.gather(choose(a, 0), choose(b, 1))
            await a.reload()
            await a.locator('[data-choice="1"]').wait_for()
            assert (await state(a))["phase"] == "predict"
            await contexts[1].set_offline(True)
            await b.wait_for_timeout(1600)
            await choose(a, 1)
            await contexts[1].set_offline(False)
            await b.reload()
            await choose(b, 0)
            await asyncio.gather(*(x.locator("#next").wait_for() for x in (a, b)))
            left, right = await asyncio.gather(state(a), state(b))
            assert left["history"] == right["history"]
            assert left["scores"] == right["scores"] == [2, 2]
            # Retour depuis une autre page du site : l’état vient toujours du serveur.
            await a.goto(URL + "/confidentialite.html")
            await a.go_back()
            await a.locator("#next").wait_for()
            assert (await state(a))["scores"] == [2, 2]
            assert not errors, errors
            print("OK · deux Chromium indépendants · iPhone 13 / Pixel 7 · parcours Miroir")
        finally:
            await asyncio.gather(*(b.close() for b in browsers))

if __name__ == "__main__":
    asyncio.run(main())
