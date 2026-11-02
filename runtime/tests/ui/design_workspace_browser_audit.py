"""Real isolated Design API + CPU pool + Chromium audit. No production imports."""
from contextlib import contextmanager
from dataclasses import replace
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import tempfile
import threading
import time

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from playwright.sync_api import expect, sync_playwright
import uvicorn
import yaml

from utils.compute_pool import ComputePool
from utils.runtime_paths import current_paths
from workspaces.design.api import create_router
from workspaces.design.catalog import DEFAULT_ROOT, DesignCatalog
from workspaces.design.service import DesignService

ROOT = Path(__file__).resolve().parents[2]
MODULE = 'metamaterial_unit_cell_designer'
CHROMIUM = '/home/jin/.cache/ms-playwright/chromium-1243/chrome-linux-arm64/chrome'


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
        geometry_file.write_text(yaml.safe_dump(geometry))
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
        page.locator('#preview-resolution').fill('17.5')
        page.get_by_role('button',name='Preview',exact=True).click()
        expect(page.locator('#design-message')).to_contain_text('resolution must be an integer')
        page.locator('#preview-resolution').fill('48')
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
        # Saving an existing final profile must not silently change its quality/resolution.
        pinned = service.create_profile({'name':'Pinned final','request':{'module_id':MODULE,
            'geometry_id':'simple_cubic','provider_version':'1.0.0','quality':'final','resolution':80}})
        page.get_by_role('button',name='Refresh modules',exact=True).click()
        page.locator('#profile-select').select_option(pinned['id'])
        expect(page.locator('#final-resolution')).to_have_value('80')
        page.get_by_role('button',name='Save profile',exact=True).click()
        expect(page.locator('#save-state')).to_have_text('Saved')
        assert service.profile(pinned['id'])['request']['quality']=='final'
        assert service.profile(pinned['id'])['request']['resolution']==80
        page.once('dialog',lambda dialog:dialog.accept())
        page.get_by_role('button',name='Delete',exact=True).click()
        expect(page.locator('#profile-select')).not_to_contain_text('Pinned final')
        page.locator('#final-resolution').fill('96')
        page.locator('#profile-select').select_option(profile_id)
        expect(page.get_by_label('Cell size',exact=True)).to_have_value('12')
        page.get_by_label('Cell size',exact=True).fill('10')
        page.get_by_role('button',name='Preview',exact=True).click()
        page.get_by_label('Cell size',exact=True).fill('14')
        print('Preview submitted; checking real STL viewer',flush=True)
        expect(page.locator('#design-viewer')).to_have_attribute('data-job-id',__import__('re').compile('.+'),timeout=40000)
        preview_id=page.locator('#design-viewer').get_attribute('data-job-id')
        expect(page.get_by_label('Cell size',exact=True)).to_have_value('14')
        expect(page.locator('#result-title')).to_contain_text('simple_cubic')
        expect(page.locator('#result-checks')).to_contain_text('Preview only')
        page.wait_for_timeout(3200)
        assert assets.count(url+f'/api/design/jobs/{preview_id}/artifacts/stl')==1,assets
        page.locator('#design-viewer').focus()
        page.keyboard.press('ArrowLeft')
        camera=page.evaluate("localStorage.getItem('ax4lab.design.camera')")
        assert camera
        page.get_by_label('Cell size',exact=True).fill('10')
        page.get_by_role('button',name='Generate',exact=True).click()
        expect(page.locator('#design-jobs article').first).to_contain_text('final 96')
        expect(page.locator('#design-jobs article').first).to_contain_text('succeeded',timeout=40000)
        expect(page.locator('#design-message')).to_have_text('Generation succeeded')
        final=service.jobs()[0]
        assert final['receipt']['final_geometry_valid'] is True
        expect(page.locator('#design-viewer')).to_have_attribute('data-job-id',preview_id)
        assert not any(final['id'] in asset for asset in assets)
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
        page.get_by_role('button',name='Refresh modules',exact=True).click()
        expect(page.locator('#design-modules article')).to_have_count(3)
        page.locator('#geometry-select').select_option('gyroid')
        expect(page.get_by_label('Orientation · X / Y / Z 1')).to_be_disabled()
        page.locator('#representation-select').select_option('network_positive')
        expect(page.get_by_label('Orientation · X / Y / Z 1')).to_be_enabled()
        page.locator('#geometry-select').select_option('spinodoid')
        page.get_by_label('Seed',exact=True).fill('42')
        page.locator('#final-resolution').fill('160')
        page.get_by_role('button',name='Generate',exact=True).click()
        try:
            expect(page.locator('#design-jobs article').first).to_contain_text('spinodoid')
        except AssertionError:
            print({'message':page.locator('#design-message').inner_text(),
                'seed':page.get_by_label('Seed',exact=True).input_value(),
                'geometry':page.locator('#geometry-select').input_value(),
                'errors':errors},flush=True)
            raise
        page.locator('#preview-resolution').fill('17.5')
        page.get_by_role('button',name='Preview',exact=True).click()
        expect(page.locator('#design-message')).to_contain_text('resolution must be an integer')
        page.locator('#design-jobs article').first.get_by_role('button',name='Cancel').click()
        expect(page.locator('#design-jobs article').first).to_contain_text('cancelled')
        expect(page.locator('#design-message')).to_contain_text('resolution must be an integer')
        expect(page.locator('#design-jobs article').first.get_by_text('Download STL')).to_have_count(0)
        expect(page.locator('#result-title')).to_contain_text('simple_cubic')
        page.get_by_role('button',name='Disable Metamaterial Unit Cell Designer').click()
        expect(page.get_by_role('button',name='Preview',exact=True)).to_be_disabled()
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
        page.locator(f'[data-job-id="{preview_id}"]').get_by_role('button',name='View preview').click()
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
            'requests':len(requests),'checks':'catalog, visibility, dirty inputs, numeric error, profile conflict, real preview/final download, camera, cancel, removal, reload, narrow'}
        (output/'evidence.json').write_text(json.dumps(evidence,indent=2))
        browser.close()
        print(json.dumps(evidence,indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--output',type=Path,default=Path(tempfile.mkdtemp(prefix='design-qa-')))
    parser.add_argument('--chromium',default=CHROMIUM)
    args=parser.parse_args()
    audit(args.output,args.chromium)
