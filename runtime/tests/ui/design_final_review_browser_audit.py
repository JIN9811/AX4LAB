"""Only final-review profile races and declarative controls; no numerical jobs."""
import asyncio
import json
from pathlib import Path
import tempfile

from design_workspace_browser_audit import fixture_server, async_playwright, async_expect, CHROMIUM, MODULE
import yaml


async def audit():
    output = Path(tempfile.mkdtemp(prefix="design-final-review-browser-"))
    evidence = []
    with tempfile.TemporaryDirectory(prefix="design-final-review-host-") as temporary, fixture_server(Path(temporary)) as (url, service, modules, pool):
        path = modules / "fixture_two/module.yaml"
        descriptor = yaml.safe_load(path.read_text())
        descriptor["actions"] = ["preview"]
        path.write_text(yaml.safe_dump(descriptor))
        service.refresh()
        def req(module, geometry):
            return {"module_id":module, "geometry_id":geometry, "provider_version":"1.0.0", "quality":"preview"}
        a = service.create_profile({"name":"A", "request":req("fixture_two", "fixture_shape")})
        b = service.create_profile({"name":"B", "request":req(MODULE, "simple_cubic")})
        missing = service.create_profile({"name":"Unavailable", "request":req("fixture_three", "fixture_shape")})
        service.module_state("fixture_three", enabled=False, revision=1)
        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(executable_path=CHROMIUM, headless=True)
            for case in ("new", "empty", "unavailable", "capabilities", "delete_other"):
                page = await browser.new_page(viewport={"width":1440,"height":1000})
                errors = []
                page.on("pageerror", lambda error: errors.append(str(error)))
                gate, entered = asyncio.Event(), asyncio.Event()
                try:
                    await page.goto(url + "/design")
                    assert "Design" in await page.title()
                    await async_expect(page.locator("#profile-select")).to_contain_text("B")
                    await page.evaluate('''() => {
                        for (const [id,event] of [['profile-select','onchange'],['delete-profile','onclick']]) {
                            const el=document.getElementById(id), fn=el[event];
                            el[event]=async function(e) {window[id+'Pending']=(window[id+'Pending']||0)+1;
                                try {await fn.call(this,e);} finally {window[id+'Pending']--;}};
                        }
                    }''')
                    async def choose(identity):
                        await page.locator("#profile-select").select_option(identity)
                        await page.wait_for_function("window['profile-selectPending'] === 0")
                    await choose(b["id"])
                    if case == "capabilities":
                        await choose(a["id"])
                        await async_expect(page.locator("#preview-design")).to_be_enabled()
                        await async_expect(page.locator("#generate-design")).to_be_disabled()
                        await async_expect(page.locator("#selection-state")).to_contain_text("Manual only")
                        await page.screenshot(path=str(output / "capabilities.png"))
                        await choose(b["id"])
                        await async_expect(page.locator("#generate-design")).to_be_enabled()
                        await async_expect(page.locator("#selection-state")).to_contain_text("Agent handoff supported")
                    else:
                        async def delayed(route):
                            response = await route.fetch()
                            entered.set()
                            await gate.wait()
                            await route.fulfill(response=response)
                        if case == "delete_other":
                            await choose(a["id"])
                            await page.route("**/profiles/"+a["id"], delayed)
                            page.once("dialog", lambda dialog: dialog.accept())
                            await page.locator("#delete-profile").click()
                            await asyncio.wait_for(entered.wait(),5)
                            await choose(b["id"])
                        else:
                            await page.route("**/modules/fixture_two/geometries", delayed)
                            await page.locator("#profile-select").select_option(a["id"])
                            await asyncio.wait_for(entered.wait(),5)
                            if case == "new": await page.locator("#new-profile").click()
                            else: await page.locator("#profile-select").select_option("" if case == "empty" else missing["id"])
                        gate.set()
                        await page.wait_for_function("window['delete-profilePending'] === 0" if case == "delete_other"
                                                     else "window['profile-selectPending'] === 0")
                        await async_expect(page.locator("#geometry-select")).to_have_value("simple_cubic")
                        if case == "delete_other":
                            await async_expect(page.locator("#profile-name")).to_have_value("B")
                        else:
                            if case == "unavailable": await page.locator("#new-profile").click()
                            await page.locator("#profile-name").fill("Draft " + case)
                        async with page.expect_response(lambda r:"/api/design/profiles" in r.url and r.request.method in ("POST","PUT")) as submitted:
                            await page.locator("#save-profile").click()
                        response = await submitted.value
                        actual = response.request.post_data_json
                        assert response.status in (200,201), await response.text()
                        assert actual["request"]["module_id"] == MODULE, actual
                        assert actual["request"]["geometry_id"] == "simple_cubic", actual
                        if case == "delete_other": assert response.request.url.endswith("/" + b["id"])
                        evidence.append({"case":case,"actual_request":actual,"status":response.status})
                    assert not errors, errors
                    if case == "capabilities": evidence.append({"case":case,"passed":True})
                finally:
                    gate.set()
                    await page.close()
            assert service.jobs() == []
            await browser.close()
    (output / "evidence.json").write_text(json.dumps(evidence,indent=2))
    print(json.dumps({"output":str(output),"passed":len(evidence),"cases":evidence},indent=2))


if __name__ == "__main__":
    asyncio.run(audit())
