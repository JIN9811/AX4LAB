"""Installed-wheel consumers must work without the checkout on sys.path."""
import ast
import os
from pathlib import Path
import subprocess
import sys
import zipfile

RUNTIME = Path(__file__).resolve().parents[2]


def test_main_binding_registers_design_without_numerical_imports(tmp_path):
    # Execute only the actual host's Design binding, not its equipment bootstrap.
    tree = ast.parse((RUNTIME / 'app/main.py').read_text())
    nodes = [node for node in tree.body if
             isinstance(node, ast.ImportFrom) and node.module == 'workspaces.design.host' or
             isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) and
             isinstance(node.value.func, ast.Name) and node.value.func.id == 'install_design_workspace']
    script = """
import sys
from pathlib import Path
from types import SimpleNamespace
from fastapi import FastAPI
app = FastAPI()
RUNTIME_PATHS = SimpleNamespace(memory_root=Path('memory'), artifact_root=Path('artifacts'))
templates = None
""" + ast.unparse(ast.Module(body=nodes, type_ignores=[])) + """
assert str(app.url_path_for('workspace')) == '/design'
assert not Path('memory').exists()
assert not any(name in sys.modules for name in ('numpy', 'scipy', 'trimesh', 'serial', 'workspaces.design.service'))
"""
    result = subprocess.run([sys.executable, '-c', script], cwd=tmp_path,
        env={**os.environ, 'PYTHONPATH': str(RUNTIME)}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


def test_extracted_wheel_discovers_sources_and_serves_gui_api(tmp_path):
    build = subprocess.run([sys.executable, 'setup.py', 'egg_info', '--egg-base', str(tmp_path),
        'build', '--build-base', str(tmp_path/'build'), 'bdist_wheel',
        '--bdist-dir', str(tmp_path/'bdist'), '--dist-dir', str(tmp_path/'dist')],
        cwd=RUNTIME, capture_output=True, text=True)
    assert build.returncode == 0, build.stderr[-6000:]
    wheel = next((tmp_path/'dist').glob('*.whl'))
    target = tmp_path/'installed'
    with zipfile.ZipFile(wheel) as archive:
        archive.extractall(target)
    script = """
import sys
import re
from pathlib import Path
sys.path.insert(0, sys.argv[1])
root = Path(sys.argv[1])
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from types import SimpleNamespace
from workspaces.design.host import install_design_workspace
assert not any(n in sys.modules for n in ('numpy', 'trimesh', 'serial'))
from workspaces.design.catalog import DesignCatalog
catalog = DesignCatalog()
assert not catalog.errors, catalog.errors
assert len(catalog.geometries) == 14
assert Path(sys.modules['workspaces.design.catalog'].__file__).is_relative_to(root)
for record in catalog.geometries.values():
    assert 'utils/source_identity.py' in record['source_files']
    assert record['provider_path'].is_file() and record['descriptor_path'].is_file()
from workspaces.design.engine import normalize_request
assert normalize_request(dict(module_id='metamaterial_unit_cell_designer',geometry_id='simple_cubic',provider_version='1.0.0'),catalog)['resolution'] == 48
from agents.design import geometry_adapter
assert Path(geometry_adapter.__file__).is_relative_to(root)
from workspaces.design.engine import generate_geometry
receipt = generate_geometry(dict(module_id='metamaterial_unit_cell_designer',geometry_id='simple_cubic',provider_version='1.0.0',quality='final',resolution=96),Path('mesh'),identity={},catalog=catalog)
assert receipt['final_geometry_valid'] and receipt['checks']['stl_reload'] == 'passed'
resources = root/'_autonomous_researcher_resources/web'
app = FastAPI()
app.mount('/static', StaticFiles(directory=resources/'static'), name='static')
install_design_workspace(app, SimpleNamespace(memory_root=Path('memory'),artifact_root=Path('artifacts')), Jinja2Templates(directory=resources/'templates'))
with TestClient(app, base_url='http://localhost', client=('127.0.0.1',1)) as c:
    page = c.get('/design')
    assert page.status_code == 200
    assert len(c.get('/api/design/modules/metamaterial_unit_cell_designer/geometries').json()['geometries']) == 14
    for asset in ('design_workspace.js','design_workspace.css','workspace_icons/design.svg'):
        assert c.get('/static/'+asset).status_code == 200, asset
    for asset in re.findall(r'(?:src|href)="(/static/[^" ]+)"', page.text):
        assert c.get(asset).status_code == 200, asset
"""
    result = subprocess.run([sys.executable, '-I', '-c', script, str(target)], cwd=tmp_path,
        env={k:v for k,v in os.environ.items() if k != 'PYTHONPATH'}, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
