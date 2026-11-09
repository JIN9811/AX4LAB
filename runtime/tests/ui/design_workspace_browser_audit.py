"""Real isolated Design API + CPU pool + Chromium audit. No production imports."""
from contextlib import contextmanager
from dataclasses import replace
import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
import threading
import time
import traceback

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from playwright.sync_api import expect, sync_playwright
from playwright.async_api import expect as async_expect, async_playwright
import uvicorn
import yaml

from utils.compute_pool import ComputePool
from utils.runtime_paths import current_paths
from workspaces.design.api import create_router
from workspaces.design.catalog import DEFAULT_ROOT, DesignCatalog
from workspaces.design.service import DesignService

ROOT = Path(__file__).resolve().parents[2]
MODULE = 'metamaterial_unit_cell_designer'
CHROMIUM = os.environ.get('AX4LAB_TEST_CHROMIUM') or None


@contextmanager
def fixture_server(root):
    private = {name:root/name for name in ('run_root','memory_root','artifact_root','output_root',
        'source_inbox_root','user_file_root','log_root')}
    paths = replace(current_paths(), **private)
    bindings = root/'bindings.json'
    bindings.write_text(json.dumps({'schema':'atr.path_bindings.v1','stores':{k:str(v) for k,v in private.items()}}))
    previous = os.environ.get('ATR_PATH_BINDINGS')
    os.environ['ATR_PATH_BINDINGS'] = str(bindings)
    modules = root/'modules'
    shutil.copytree(DEFAULT_ROOT, modules)
    for key, label in [('fixture_two','Second Fixture'),('fixture_three','Third Fixture')]:
        folder = modules/key
        folder.mkdir()
        for name in ('module.yaml','provider.py','icon.svg'):
            shutil.copy2(DEFAULT_ROOT/MODULE/name, folder/name)
        descriptor = yaml.safe_load((folder/'module.yaml').read_text())
        descriptor.update(id=key,label=label)
        (folder/'module.yaml').write_text(yaml.safe_dump(descriptor))
        shutil.copytree(DEFAULT_ROOT/MODULE/'geometries/simple_cubic',folder/'geometries/fixture_shape')
        geometry_file = folder/'geometries/fixture_shape/module.yaml'
        geometry = yaml.safe_load(geometry_file.read_text())
        geometry.update(id='fixture_shape',label='Fixture Shape')
        geometry['fields'] += [{'key':'mode','label':'Fixture mode','type':'enum','options':['plain','detail']},
            {'key':'note','label':'Fixture note','type':'text','visible_when':{'field':'mode','equals':'detail'}}]
        geometry['defaults'].update(mode='plain',note='retained')
        geometry.setdefault('parameter_roles', {}).update(mode='fixed', note='fixed')
        geometry_file.write_text(yaml.safe_dump(geometry))
        # Explicit fixture wrapper owns its graph; its public identity is not a
        # built-in graph name. It is deliberately manual-only.
        geometry['agent_handoff'] = False
        geometry_file.write_text(yaml.safe_dump(geometry))
        (geometry_file.parent/'provider.py').write_text(
            'from workspaces.design.providers.strut import generate_field as field\n'
            'from workspaces.design.providers.preflight import strut\n'
            'def preflight(request):\n'
            '    return strut({**request, "geometry_id":"simple_cubic"})\n'
            'def generate_field(grid, request):\n'
            '    return field(grid, {**request, "geometry_id":"simple_cubic"})\n')
    pool = ComputePool(1, paths=paths)
    service = DesignService(paths.memory_root,paths.artifact_root,catalog=DesignCatalog(modules),executor=pool)
    app = FastAPI()
    app.mount('/static',StaticFiles(directory=ROOT/'web/static'),name='static')
    app.include_router(create_router(service,Jinja2Templates(directory=ROOT/'web/templates')))
    sock = socket.socket()
    sock.bind(('127.0.0.1',0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app,log_level='error'))
    thread = threading.Thread(target=lambda:server.run(sockets=[sock]),daemon=True)
    thread.start()
    try:
        deadline = time.monotonic()+10
        while not server.started and time.monotonic()<deadline:
            time.sleep(.01)
        assert server.started
        yield f'http://127.0.0.1:{port}',service,modules,pool
    finally:
        server.should_exit=True
        thread.join(10)
        service.shutdown()
        pool.close()
        sock.close()
        if previous is None:
            os.environ.pop('ATR_PATH_BINDINGS',None)
        else:
            os.environ['ATR_PATH_BINDINGS']=previous


def audit(output, chromium):
    output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='design-browser-') as temporary, fixture_server(Path(temporary)) as (url,service,modules,pool), sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=chromium,headless=True,args=['--enable-unsafe-swiftshader'])
        context = browser.new_context(viewport={'width':1920,'height':1080},accept_downloads=True)
        page = context.new_page()
        errors,requests,assets,render_warnings = [],[],[],[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        def console_message(msg):
            if msg.type not in ('error','warning'):
                return
            if 'GPU stall due to ReadPixels' in msg.text:
                render_warnings.append(msg.text)
            elif 'status of 422' not in msg.text and 'status of 409' not in msg.text:
                errors.append(msg.text)
        page.on('console',console_message)
        page.on('request',lambda request:requests.append(request.url))
        page.on('request',lambda request:assets.append(request.url) if '/artifacts/stl' in request.url else None)
        page.goto(url+'/design')
        expect(page).to_have_title('Design · AX4LAB')
        expect(page.get_by_role('heading',name='Design',exact=True)).to_be_visible()
        expect(page.locator('#design-modules article')).to_have_count(3)
        page.screenshot(path=str(output/'catalog.png'),full_page=True,animations='disabled')
        assert page.get_by_role('button',name='Third Fixture',exact=True).bounding_box()['width'] > 100
        page.get_by_role('button',name='Third Fixture',exact=True).click()
        page.locator('#design-settings-panel').evaluate('(e)=>e.open=true')
        expect(page.get_by_label('Fixture mode')).to_be_visible()
        expect(page.get_by_label('Fixture note')).to_be_hidden()
        page.get_by_label('Fixture mode').select_option('detail')
        expect(page.get_by_label('Fixture note')).to_have_value('retained')
        page.get_by_role('button',name='Metamaterial Unit Cell Designer',exact=True).click()
        page.locator('#geometry-select').select_option('simple_cubic')
        page.screenshot(path=str(output/'initial-desktop.png'),full_page=True,animations='disabled')
        print(f'Rendered page: {output / "initial-desktop.png"}',flush=True)
        page.get_by_label('Cell size',exact=True).fill('11')
        page.get_by_role('button',name='Refresh modules',exact=True).click()
        expect(page.get_by_label('Cell size',exact=True)).to_have_value('11')
        page.locator('#final-resolution').fill('17.5')
        page.get_by_role('button',name='Generate STL',exact=True).click()
        expect(page.locator('#design-message')).to_contain_text('resolution must be an integer')
        page.locator('#final-resolution').fill('128')
        page.get_by_label('Cell size',exact=True).fill('10')
        page.get_by_label('Profile name',exact=True).fill('Browser cubic')
        page.get_by_role('button',name='Save profile',exact=True).click()
        expect(page.locator('#save-state')).to_have_text('Saved')
        profile_id = page.locator('#profile-select').input_value()
        second = context.new_page()
        second.goto(url+'/design')
        second.locator('#profile-select').select_option(profile_id)
        expect(second.get_by_label('Cell size',exact=True)).to_have_value('10')
        page.get_by_label('Cell size',exact=True).fill('12')
        page.get_by_role('button',name='Save profile',exact=True).click()
        expect(page.locator('#save-state')).to_have_text('Saved')
        second.get_by_label('Cell size',exact=True).fill('13')
        second.get_by_role('button',name='Save profile',exact=True).click()
        expect(second.locator('#design-message')).to_contain_text('Stale or invalid revision')
        expect(second.get_by_label('Cell size',exact=True)).to_have_value('13')
        second.close()
        # A legacy low-resolution profile is upgraded only in the editing draft.
        pinned = service.create_profile({'name':'Pinned final','request':{'module_id':MODULE,
            'geometry_id':'simple_cubic','provider_version':'1.0.0','quality':'final','resolution':80}})
        page.get_by_role('button',name='Refresh modules',exact=True).click()
        page.locator('#profile-select').select_option(pinned['id'])
        expect(page.locator('#final-resolution')).to_have_value('128')
        assert service.profile(pinned['id'])['request']['resolution']==80
        page.get_by_role('button',name='Save profile',exact=True).click()
        expect(page.locator('#save-state')).to_have_text('Saved')
        assert service.profile(pinned['id'])['request']['quality']=='final'
        assert service.profile(pinned['id'])['request']['resolution']==128
        page.once('dialog',lambda dialog:dialog.accept())
        page.get_by_role('button',name='Delete',exact=True).click()
        expect(page.locator('#profile-select')).not_to_contain_text('Pinned final')
        page.locator('#final-resolution').fill('96')
        page.locator('#profile-select').select_option(profile_id)
        expect(page.get_by_label('Cell size',exact=True)).to_have_value('12')
        page.get_by_label('Cell size',exact=True).fill('10')
        page.get_by_role('button',name='Generate STL',exact=True).click()
        page.get_by_label('Cell size',exact=True).fill('14')
        print('Final STL submitted; checking the same-file viewer',flush=True)
        expect(page.locator('#design-viewer')).to_have_attribute('data-job-id',__import__('re').compile('.+'),timeout=40000)
        preview_id=page.locator('#design-viewer').get_attribute('data-job-id')
        expect(page.get_by_label('Cell size',exact=True)).to_have_value('14')
        expect(page.locator('#result-title')).to_contain_text('simple_cubic')
        assert service.job(preview_id)['receipt']['final_geometry_valid'] is True
        page.wait_for_timeout(3200)
        assert assets.count(url+f'/api/design/jobs/{preview_id}/artifacts/stl')==1,assets
        page.locator('#design-viewer').focus()
        page.keyboard.press('ArrowLeft')
        camera=page.evaluate("localStorage.getItem('ax4lab.design.camera')")
        assert camera
        page.get_by_label('Cell size',exact=True).fill('10')
        page.locator('#final-resolution').fill('96')
        page.get_by_role('button',name='Generate STL',exact=True).click()
        expect(page.locator('#design-jobs article').first).to_contain_text('final 96')
        expect(page.locator('#design-jobs article').first).to_contain_text('succeeded',timeout=40000)
        expect(page.locator('#design-message')).to_have_text('STL generation succeeded')
        final=service.jobs()[0]
        assert final['receipt']['final_geometry_valid'] is True
        expect(page.locator('#design-viewer')).to_have_attribute('data-job-id',final['id'])
        assert assets.count(url+f'/api/design/jobs/{final["id"]}/artifacts/stl')==1
        jobs_before_color = len(service.jobs())
        page.locator('#stl-color').fill('#ea6d45')
        assert page.evaluate("localStorage.getItem('ax4lab.design.color')") == '#ea6d45'
        assert len(service.jobs()) == jobs_before_color
        with page.expect_download() as download:
            page.locator('#design-jobs article').first.get_by_text('Download STL').click()
        destination=output/'actual-final.stl'
        download.value.save_as(destination)
        assert hashlib.sha256(destination.read_bytes()).hexdigest()==final['receipt']['artifacts']['stl']['sha256']
        page.screenshot(path=str(output/'desktop.png'),full_page=True,animations='disabled')
        for fixture in ('fixture_two','fixture_three'):
            (modules/fixture).rename(Path(temporary)/fixture)
        page.get_by_role('button',name='Refresh modules',exact=True).click()
        expect(page.locator('#design-modules article')).to_have_count(1)
        page.screenshot(path=str(output/'real-desktop.png'),full_page=True,animations='disabled')
        page.evaluate('scrollTo(0,0)')
        page.screenshot(path=str(output/'real-desktop-viewport.png'),animations='disabled')
        page.set_viewport_size({'width':390,'height':844})
        page.evaluate('scrollTo(0,0)')
        page.screenshot(path=str(output/'real-narrow.png'),animations='disabled')
        page.locator('.design-result').scroll_into_view_if_needed()
        expect(page.locator('#result-checks')).to_be_visible()
        assert page.locator('.design-result').evaluate('(e)=>getComputedStyle(e).opacity') == '1'
        page.screenshot(path=str(output/'real-narrow-result.png'),animations='disabled')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.set_viewport_size({'width':1920,'height':1080})
        for fixture in ('fixture_two','fixture_three'):
            (Path(temporary)/fixture).rename(modules/fixture)
        with page.expect_response(lambda response:response.url.endswith(f'/modules/{MODULE}/geometries')) as refreshed:
            page.get_by_role('button',name='Refresh modules',exact=True).click()
        refreshed.value.body()
        page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
        expect(page.locator('#design-modules article')).to_have_count(3)
        page.locator('#geometry-select').select_option('gyroid')
        expect(page.get_by_label('Orientation · X / Y / Z 1')).to_be_disabled()
        page.locator('#representation-select').select_option('network_positive')
        expect(page.get_by_label('Orientation · X / Y / Z 1')).to_be_enabled()
        page.locator('#geometry-select').select_option('spinodoid')
        page.get_by_label('Seed',exact=True).fill('42')
        page.locator('#final-resolution').fill('160')
        with page.expect_response(lambda response:response.url.endswith('/api/design/jobs') and response.request.method=='POST') as submitted:
            page.get_by_role('button',name='Generate STL',exact=True).click()
        submit_response=submitted.value
        cancelled_job=submit_response.json()
        assert submit_response.status==202,cancelled_job
        assert cancelled_job['request']['geometry_id']=='spinodoid',cancelled_job
        assert cancelled_job['request']['seed']==42,cancelled_job
        assert cancelled_job['request']['resolution']==160,cancelled_job
        cancelled_row=page.locator(f'#design-jobs [data-job-id="{cancelled_job["id"]}"]')
        expect(cancelled_row).to_contain_text('spinodoid')
        page.locator('#final-resolution').fill('17.5')
        page.get_by_role('button',name='Generate STL',exact=True).click()
        expect(page.locator('#design-message')).to_contain_text('resolution must be an integer')
        cancelled_row.get_by_role('button',name='Cancel').click()
        expect(cancelled_row).to_contain_text('cancelled')
        expect(page.locator('#design-message')).to_contain_text('resolution must be an integer')
        expect(cancelled_row.get_by_text('Download STL')).to_have_count(0)
        expect(page.locator('#result-title')).to_contain_text('simple_cubic')
        page.get_by_role('button',name='Disable Metamaterial Unit Cell Designer').click()
        expect(page.get_by_role('button',name='Generate STL',exact=True)).to_be_disabled()
        expect(page.locator('#profile-select')).to_contain_text('Browser cubic · Unavailable')
        expect(page.locator('#result-download')).to_be_visible()
        page.get_by_role('button',name='Third Fixture',exact=True).click()
        expect(page.get_by_label('Fixture mode')).to_be_visible()
        expect(page.get_by_role('button',name='Save profile',exact=True)).to_be_enabled()
        page.locator('#profile-select').select_option(profile_id)
        expect(page.get_by_role('button',name='Save profile',exact=True)).to_be_disabled()
        page.get_by_role('button',name='New',exact=True).click()
        expect(page.get_by_role('button',name='Save profile',exact=True)).to_be_enabled()
        # Remove only a temporary installed module; the receipt and artifact remain available.
        shutil.rmtree(modules/MODULE)
        page.get_by_role('button',name='Refresh modules',exact=True).click()
        expect(page.locator('#design-modules article')).to_have_count(2)
        expect(page.locator('#profile-select')).to_contain_text('Browser cubic · Unavailable')
        page.reload()
        expect(page.locator('#design-jobs article')).to_have_count(3)
        expect(page.locator('#profile-select')).to_contain_text('Browser cubic · Unavailable')
        page.locator(f'#design-jobs [data-job-id="{preview_id}"]').get_by_role('button',name='View STL').click()
        expect(page.locator('#stl-color')).to_have_value('#ea6d45')
        expect(page.locator('#design-viewer')).to_have_attribute('data-job-id',preview_id)
        assert json.loads(page.evaluate("localStorage.getItem('ax4lab.design.camera')"))==json.loads(camera)
        page.get_by_role('button',name='Third Fixture',exact=True).click()
        page.set_viewport_size({'width':390,'height':844})
        page.screenshot(path=str(output/'narrow.png'),full_page=True,animations='disabled')
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert not errors,errors
        assert all(u.startswith(url+'/static/') or u.startswith(url+'/api/design/') or u==url+'/design' for u in requests),requests
        assert pool.status()['completed']>=2
        evidence={'url':url+'/design','viewports':['1920x1080','390x844'],'browser':'Playwright; Browser plugin not available',
            'errors':errors,'software_renderer_warnings':render_warnings,'preview_id':preview_id,'final_id':final['id'],'final_bytes':destination.stat().st_size,
            'requests':len(requests),'cancelled_job':{key:cancelled_job[key] for key in ('id','request','request_sha256','created_sequence')},
            'checks':'catalog, visibility, dirty inputs, numeric error, profile conflict, same final STL viewing/download, color, camera, cancel, removal, reload, narrow'}
        (output/'evidence.json').write_text(json.dumps(evidence,indent=2))
        browser.close()
        print(json.dumps(evidence,indent=2))


def parameter_probe(output, chromium):
    """Real stochastic final meshes, public input contracts, and viewer-only color."""
    output.mkdir(parents=True, exist_ok=True)
    evidence = []
    with tempfile.TemporaryDirectory(prefix='design-parameters-') as temporary, fixture_server(Path(temporary)) as (url, service, modules, pool), sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=chromium, headless=True, args=['--enable-unsafe-swiftshader'])
        page = browser.new_page(viewport={'width':1920, 'height':1080}, accept_downloads=True)
        errors, posts = [], []
        page.on('pageerror', lambda error:errors.append(str(error)))
        page.on('request', lambda request:posts.append(request.post_data_json) if request.method=='POST' and request.url.endswith('/api/design/jobs') else None)
        page.goto(url+'/design')
        page.get_by_role('button', name='Metamaterial Unit Cell Designer', exact=True).click()
        expect(page.locator('#preview-resolution')).to_have_count(0)
        for geometry in ('spinodoid', 'voronoi'):
            page.locator('#geometry-select').select_option(geometry)
            expect(page.get_by_label('Seed', exact=True)).to_have_value('42')
            expect(page.locator('#final-resolution')).to_have_value('128')
            contract_response = page.request.get(url+f'/api/design/modules/{MODULE}/geometries/{geometry}/contract')
            assert contract_response.status == 200
            contract = contract_response.json()
            assert contract['request_template']['seed'] == 42
            if geometry == 'spinodoid':
                expect(page.locator('#design-settings').get_by_label('Wave count', exact=True)).to_have_count(1)
                expect(page.locator('#design-fields').get_by_label('GRF wavelength', exact=True)).to_be_visible()
            with page.expect_response(lambda r:r.request.method=='POST' and r.url.endswith('/api/design/jobs')) as submitted:
                page.get_by_role('button', name='Generate STL', exact=True).click()
            assert submitted.value.status == 202, submitted.value.text()
            job_id = submitted.value.json()['id']
            expect(page.locator('#design-viewer')).to_have_attribute('data-job-id', job_id, timeout=120000)
            job = service.job(job_id)
            assert job['state'] == 'succeeded', job
            assert job['request']['quality'] == 'final'
            assert job['request']['resolution'] == 128
            assert job['receipt']['final_geometry_valid'] is True
            with page.expect_download() as download:
                page.locator('#result-download').click()
            destination = output/f'{geometry}.stl'
            download.value.save_as(destination)
            digest = hashlib.sha256(destination.read_bytes()).hexdigest()
            assert digest == job['receipt']['artifacts']['stl']['sha256']
            before = len(posts)
            page.locator('#stl-color').fill('#3d94b8')
            original_pixels = page.locator('#design-viewer').screenshot()
            page.locator('#stl-color').fill('#ea6d45')
            changed_pixels = page.locator('#design-viewer').screenshot()
            assert original_pixels != changed_pixels, 'Color control must change rendered mesh pixels'
            assert page.evaluate("localStorage.getItem('ax4lab.design.color')") == '#ea6d45'
            assert len(posts) == before
            page.screenshot(path=str(output/f'{geometry}.png'), full_page=True)
            evidence.append({'geometry':geometry, 'job_id':job_id, 'resolution':128,
                'final_geometry_valid':True, 'stl_bytes':destination.stat().st_size, 'sha256':digest,
                'contract_roles':{p['key']:p['role'] for p in contract['parameters']}})
        page.reload()
        expect(page.locator('#stl-color')).to_have_value('#ea6d45')
        assert len(posts) == 2, posts
        assert not errors, errors
        browser.close()
    (output/'parameter-evidence.json').write_text(json.dumps(evidence, indent=2))
    print(json.dumps(evidence, indent=2), flush=True)


async def selection_probe(output,chromium):
    """Bound three refresh interleavings, using real API responses and exact POST IDs."""
    output.mkdir(parents=True,exist_ok=True)
    results=[]
    with tempfile.TemporaryDirectory(prefix='design-selection-') as temporary, fixture_server(Path(temporary)) as (url,service,modules,pool):
        async with async_playwright() as playwright:
            browser=await playwright.chromium.launch(executable_path=chromium,headless=True,args=['--enable-unsafe-swiftshader'])
            for phase in ('before_seed','after_seed','after_submit'):
                page=await browser.new_page(viewport={'width':1920,'height':1080})
                posts=[]
                page.on('request',lambda request:posts.append(request.post_data_json) if request.url.endswith('/api/design/jobs') and request.method=='POST' else None)
                await page.goto(url+'/design')
                await page.get_by_role('button',name='Metamaterial Unit Cell Designer',exact=True).click()
                await async_expect(page.locator('#geometry-select')).to_be_visible()
                await page.locator('#geometry-select').select_option('simple_cubic')
                await page.set_viewport_size({'width':390,'height':844})
                await page.locator('#generate-design').scroll_into_view_if_needed()
                await page.set_viewport_size({'width':1920,'height':1080})
                gate,entered=asyncio.Event(),asyncio.Event()
                async def delayed(route):
                    entered.set()
                    await gate.wait()
                    await route.continue_()
                await page.route(f'**/modules/{MODULE}/geometries',delayed)
                await page.get_by_role('button',name='Refresh modules',exact=True).click()
                await asyncio.wait_for(entered.wait(),5)
                await page.locator('#geometry-select').select_option('gyroid')
                await async_expect(page.get_by_label('Orientation · X / Y / Z 1')).to_be_disabled()
                await page.locator('#representation-select').select_option('network_positive')
                await async_expect(page.get_by_label('Orientation · X / Y / Z 1')).to_be_enabled()
                await page.locator('#geometry-select').select_option('spinodoid')
                async def release_refresh():
                    async with page.expect_response(lambda response:response.url.endswith(f'/modules/{MODULE}/geometries')) as refreshed:
                        gate.set()
                    response=await refreshed.value
                    assert response.status==200
                    await response.body()
                    await page.evaluate('()=>new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)))')
                if phase=='before_seed':
                    await release_refresh()
                await page.get_by_label('Seed',exact=True).fill('42')
                await page.locator('#final-resolution').fill('160')
                if phase=='after_seed':
                    await release_refresh()
                async with page.expect_response(lambda response:response.url.endswith('/api/design/jobs') and response.request.method=='POST') as submitted:
                    await page.get_by_role('button',name='Generate STL',exact=True).click()
                response=await submitted.value
                job=await response.json()
                assert response.status==202,job
                if phase=='after_submit':
                    await release_refresh()
                assert len(posts)==1,posts
                for request in (posts[0]['request'],job['request']):
                    assert request['geometry_id']=='spinodoid',request
                    assert request['representation']=='grf',request
                    assert request['seed']==42,request
                    assert request['resolution']==160,request
                    assert request['quality']=='final',request
                row=page.locator(f'#design-jobs [data-job-id="{job["id"]}"]')
                await async_expect(row).to_contain_text('spinodoid')
                await async_expect(page.locator('#geometry-select')).to_have_value('spinodoid')
                await async_expect(page.get_by_label('Seed',exact=True)).to_have_value('42')
                await async_expect(page.locator('#final-resolution')).to_have_value('160')
                results.append({'phase':phase,'http_status':response.status,'post_count':len(posts),
                    'submitted_request':posts[0]['request'],'job_id':job['id'],
                    'canonical_request':job['request'],'request_sha256':job['request_sha256'],
                    'row_matches_accepted_id':True,'fields_preserved':True})
                service.cancel(job['id'])
                deadline=time.monotonic()+10
                while service.active is not None and time.monotonic()<deadline:
                    await asyncio.sleep(.01)
                assert service.active is None
                await page.close()
            await browser.close()
    (output/'selection-evidence.json').write_text(json.dumps(results,indent=2))
    print(json.dumps(results,indent=2))


async def draft_probe(output,chromium):
    """Exercise actual boot/fields with real validation and delayed profile responses."""
    output.mkdir(parents=True,exist_ok=True)
    results=[]
    with tempfile.TemporaryDirectory(prefix='design-drafts-') as temporary, fixture_server(Path(temporary)) as (url,service,modules,pool):
        async with async_playwright() as playwright:
            browser=await playwright.chromium.launch(executable_path=chromium,headless=True)
            for case in ('representation_parameters','representation_orientation','save_new','save_edit','save_other'):
                page=await browser.new_page(viewport={'width':1440,'height':1000})
                gate=asyncio.Event()
                evidence={}
                try:
                    base={'module_id':MODULE,'geometry_id':'simple_cubic','provider_version':'1.0.0'}
                    original=service.create_profile({'name':'Original '+case,'request':base})
                    other=service.create_profile({'name':'Other '+case,'request':dict(base,parameters={'cell_size_mm':17})})
                    await page.goto(url+'/design')
                    await page.get_by_role('button',name='Metamaterial Unit Cell Designer',exact=True).click()
                    await async_expect(page.locator('#geometry-select')).to_be_visible()
                    if case.startswith('representation'):
                        await page.locator('#geometry-select').select_option('gyroid')
                        await page.get_by_label('Cell size',exact=True).fill('13')
                        await page.get_by_label('Orientation · X / Y / Z 3').fill('25')
                        await page.locator('#representation-select').select_option('network_positive')
                        await page.get_by_label('Cell size',exact=True).fill('21')
                        await page.get_by_label('Dimensionless iso level',exact=True).fill('0.25')
                        if case.endswith('orientation'):
                            await page.get_by_label('Orientation · X / Y / Z 1').fill('15')
                            await page.get_by_label('Orientation · X / Y / Z 2').fill('10')
                            await page.get_by_label('Orientation · X / Y / Z 3').fill('30')
                        await page.locator('#representation-select').select_option('sheet')
                        if case.endswith('parameters'):
                            await async_expect(page.get_by_label('Cell size',exact=True)).to_have_value('13')
                            await page.locator('#representation-select').select_option('network_positive')
                            await async_expect(page.get_by_label('Cell size',exact=True)).to_have_value('21')
                            await async_expect(page.get_by_label('Dimensionless iso level',exact=True)).to_have_value('0.25')
                        else:
                            await async_expect(page.get_by_label('Orientation · X / Y / Z 1')).to_be_disabled()
                            await async_expect(page.get_by_label('Orientation · X / Y / Z 1')).to_have_value('0')
                            await async_expect(page.get_by_label('Orientation · X / Y / Z 2')).to_have_value('0')
                            await async_expect(page.get_by_label('Orientation · X / Y / Z 3')).to_have_value('25')
                            for representation,wanted in [('sheet',[0,0,25]),('network_positive',[15,10,30])]:
                                await page.locator('#representation-select').select_option(representation)
                                await page.get_by_role('button',name='New',exact=True).click()
                                await page.get_by_label('Profile name',exact=True).fill('Orientation '+representation)
                                async with page.expect_response(lambda r:r.url.endswith('/profiles') and r.request.method=='POST') as saved:
                                    await page.get_by_role('button',name='Save profile',exact=True).click()
                                response=await saved.value
                                record=await response.json()
                                assert response.status==201,record
                                assert record['request']['orientation_deg']==wanted,record
                                assert record['request']['representation']==representation,record
                                evidence[representation]={'profile_id':record['id'],'normalized_orientation_deg':record['request']['orientation_deg']}
                            await page.screenshot(path=str(output/'representation-roundtrip.png'))
                    else:
                        await page.evaluate('''() => {
                            const select=document.getElementById('profile-select');
                            const handler=select.onchange;
                            select.onchange=async function(event) {
                                window.__profileLoaded=false;
                                await handler.call(this,event);
                                window.__profileLoaded=true;
                            };
                        }''')
                        await page.locator('#profile-select').select_option(original['id'])
                        await page.wait_for_function('window.__profileLoaded === true')
                        await async_expect(page.get_by_label('Cell size',exact=True)).to_have_value('10')
                        await page.get_by_label('Cell size',exact=True).fill('11')
                        entered=asyncio.Event()
                        async def delayed_save(route):
                            evidence['first_save_body']=route.request.post_data_json
                            evidence['first_save_url']=route.request.url
                            response=await route.fetch()
                            evidence['first_save_response']=await response.json()
                            entered.set()
                            await gate.wait()
                            await route.fulfill(response=response)
                        await page.route(f'**/profiles/{original["id"]}',delayed_save)
                        # Observe completion of the actual boot handler, including its
                        # asynchronous list refresh, without replacing its behavior.
                        await page.evaluate('''() => {
                            const button=document.getElementById('save-profile');
                            const handler=button.onclick;
                            button.onclick=async function(event) {
                                window.__saveFinished=false;
                                await handler.call(this,event);
                                window.__saveFinished=true;
                            };
                        }''')
                        await page.get_by_role('button',name='Save profile',exact=True).click()
                        await asyncio.wait_for(entered.wait(),5)
                        assert evidence['first_save_body']['request']['parameters']['cell_size_mm']==11,evidence
                        assert evidence['first_save_response']['id']==original['id'],evidence
                        if case=='save_new':
                            await page.get_by_role('button',name='New',exact=True).click()
                            await page.get_by_label('Profile name',exact=True).fill('New draft')
                            await page.get_by_label('Cell size',exact=True).fill('14')
                            wanted_id,wanted_name,wanted_cell='','New draft','14'
                        elif case=='save_edit':
                            await page.get_by_label('Profile name',exact=True).fill('Edited draft')
                            await page.get_by_label('Cell size',exact=True).fill('14')
                            wanted_id,wanted_name,wanted_cell=original['id'],'Edited draft','14'
                        else:
                            await page.locator('#profile-select').select_option(other['id'])
                            await page.wait_for_function('window.__profileLoaded === true')
                            await async_expect(page.get_by_label('Cell size',exact=True)).to_have_value('17')
                            await page.get_by_label('Cell size',exact=True).fill('18')
                            wanted_id,wanted_name,wanted_cell=other['id'],other['name'],'18'
                        async with page.expect_response(lambda r:r.url.endswith('/profiles/'+original['id']) and r.request.method=='PUT') as completed:
                            gate.set()
                        await (await completed.value).body()
                        await page.wait_for_function('window.__saveFinished === true')
                        await async_expect(page.locator('#profile-select')).to_have_value(wanted_id)
                        await async_expect(page.get_by_label('Profile name',exact=True)).to_have_value(wanted_name)
                        await async_expect(page.get_by_label('Cell size',exact=True)).to_have_value(wanted_cell)
                        await async_expect(page.locator('#save-state')).to_have_text('Unsaved')
                        await page.unroute(f'**/profiles/{original["id"]}',delayed_save)
                        async with page.expect_response(lambda r:'/api/design/profiles' in r.url and r.request.method in ('POST','PUT')) as final_save:
                            await page.get_by_role('button',name='Save profile',exact=True).click()
                        response=await final_save.value
                        saved=await response.json()
                        evidence['next_save_body']=response.request.post_data_json
                        evidence['next_save_response']=saved
                        assert response.status in (200,201),saved
                        assert saved['request']['parameters']['cell_size_mm']==float(wanted_cell),saved
                        if case=='save_new':
                            assert saved['id']!=original['id'],saved
                        else:
                            assert saved['id']==wanted_id,saved
                        if case!='save_edit':
                            assert service.profile(original['id'])['request']['parameters']['cell_size_mm']==11,service.profile(original['id'])
                    results.append({'case':case,'passed':True,**evidence})
                except Exception as error:
                    results.append({'case':case,'passed':False,'error':repr(error),'traceback':traceback.format_exc(),**evidence})
                finally:
                    gate.set()
                    await page.close()
            await browser.close()
    (output/'draft-evidence.json').write_text(json.dumps(results,indent=2))
    print(json.dumps(results,indent=2))
    assert all(result['passed'] for result in results),'Draft regressions failed'


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=Path(tempfile.mkdtemp(prefix='design-qa-')))
    parser.add_argument('--chromium',default=CHROMIUM)
    parser.add_argument('--selection-only',action='store_true')
    parser.add_argument('--draft-only',action='store_true')
    parser.add_argument('--parameters-only',action='store_true')
    args=parser.parse_args()
    if args.parameters_only:
        parameter_probe(args.output,args.chromium)
    elif args.draft_only:
        asyncio.run(draft_probe(args.output,args.chromium))
    elif args.selection_only:
        asyncio.run(selection_probe(args.output,args.chromium))
    else:
        audit(args.output,args.chromium)
