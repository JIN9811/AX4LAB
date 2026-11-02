"""Retained offline geometry verification; never import the production host.

Run from runtime with PYTHONPATH=. and an explicit NEW --output-root. Numerical
regressions use their own retained basetemp, not pytest's auto-pruned root.
This is deterministic graph evidence, NOT evidence of a real LLM call.
"""
import argparse
import asyncio
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from types import SimpleNamespace

MODULE = 'metamaterial_unit_cell_designer'
ALLOWED = {'geometry.generate_metamaterial_stl', 'geometry.check_mesh_quality',
           'geometry.check_manufacturability'}


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, default=str) + '\n')


async def parity(geometry, root, paths):
    from agents.base_agent import AgentContext
    from agents.design.module import DESIGN_MODULE
    from agents.specimen.module import SPECIMEN_MODULE
    from mcp_tools.mock_tools import register_mock_tools
    from mcp_tools.tool_registry import ToolRegistry
    from orchestrator.state import Mode, OrchestratorState, Stage
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from workspaces.design.api import create_router
    from workspaces.design.service import DesignService

    class GeometryOnlyRegistry(ToolRegistry):
        def __init__(self):
            super().__init__()
            self.calls = []
            register_mock_tools(self)

        def call(self, name, payload=None):
            if name not in ALLOWED:
                raise RuntimeError('Hardware/slicing denied BEFORE dispatch: ' + name)
            self.calls.append(name)
            return super().call(name, payload)

    tools = GeometryOnlyRegistry()
    try:
        tools.call('printer.start_print', {})
    except RuntimeError as exc:
        assert 'BEFORE dispatch' in str(exc) and not tools.calls
    else:
        raise AssertionError('Hardware denial was bypassed')
    memory = SimpleNamespace(list_recent=lambda _: [], recent=lambda **_: [])
    ctx = AgentContext(None, None, None, None, memory, memory, tools,
        force_real_llm_in_test=False, paths=paths, artifact_run_root=str(paths.run_root))
    request = dict(module_id=MODULE, geometry_id=geometry, provider_version='1.0.0',
                   quality='final', resolution=96)
    if geometry == 'spinodoid':
        request['seed'] = 42
    write_json(root/'input.json', request)
    service = DesignService(paths.memory_root, paths.artifact_root)
    app = FastAPI()
    app.include_router(create_router(lambda: service))
    started = time.monotonic()
    try:
        with TestClient(app, base_url='http://localhost', client=('127.0.0.1', 1)) as client:
            response = client.post('/api/design/jobs', json={'request': request, 'idempotency_key': geometry})
            assert response.status_code == 202, response.text
            accepted_id = response.json()['id']
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                job = client.get('/api/design/jobs/' + accepted_id).json()
                if job['state'] in {'succeeded', 'failed', 'cancelled', 'interrupted'}:
                    break
                await asyncio.sleep(.05)
            assert job['id'] == accepted_id and job['state'] == 'succeeded', job
            download = client.get(job['artifact_urls']['stl'])
            assert download.status_code == 200
            api_hash = hashlib.sha256(download.content).hexdigest()
            assert api_hash == job['receipt']['artifacts']['stl']['sha256']
            write_json(root/'api-job.json', job)
        state = OrchestratorState(run_id='verify-' + geometry, experiment_id='geometry-exp',
            mode=Mode.TEST, stage=Stage.DESIGN, active_goal='Offline geometry only',
            run_metadata={'orchestrator_design_contract': {'geometry_request': request}})
        result = await DESIGN_MODULE.factory().run(state, ctx)
        assert result.success, result
        spec = result.data['experiment_spec']
        write_json(root/'agent-spec.json', spec)
        agent_hash = hashlib.sha256(Path(spec['geometry_result']['stl_path']).read_bytes()).hexdigest()
        assert agent_hash == spec['geometry_receipt']['artifacts']['stl']['sha256'] == api_hash
        assert spec['geometry_receipt']['request_sha256'] == job['receipt']['request_sha256']
        assert spec['geometry_receipt']['source_fingerprint'] == job['receipt']['source_fingerprint']
        state.current_experiment_spec = deepcopy(spec)
        state.stage = Stage.SPECIMEN
        before = len(tools.calls)
        prepared = await SPECIMEN_MODULE.factory().run(state, ctx)
        assert tools.calls[before:] == ['geometry.check_mesh_quality', 'geometry.check_manufacturability']
        assert not prepared.success and prepared.data['failure_code'] == 'MANUFACTURABILITY_REJECTED'
        status = prepared.data['specimen_result']['manufacturability']['manufacturability_status']
        assert status == 'review_required'
        write_json(root/'fabrication-report.json', prepared.data['fabrication_report'])
        write_json(root/'tool-calls.json', tools.calls)
        return dict(geometry_id=geometry, ok=True, accepted_job_id=accepted_id,
            api_stl_sha256=api_hash, agent_stl_sha256=agent_hash,
            api_request_sha256=job['receipt']['request_sha256'],
            agent_request_sha256=spec['geometry_receipt']['request_sha256'],
            source_fingerprint=job['receipt']['source_fingerprint'],
            specimen_reused=True, manufacturing_status=status, seconds=time.monotonic()-started)
    finally:
        service.shutdown()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output-root', type=Path, required=True)
    parser.add_argument('--parity', nargs='+', choices=['schwarz_p', 'spinodoid', 'simple_cubic'],
                        default=['schwarz_p', 'spinodoid', 'simple_cubic'])
    parser.add_argument('--skip-regressions', action='store_true')
    args = parser.parse_args()
    root = args.output_root.absolute()
    if root.exists() or any(p.is_symlink() for p in (root, *root.parents)):
        parser.error('--output-root must be a new, non-symlink directory')
    root.mkdir(parents=True)
    runtime = Path(__file__).resolve().parents[1]
    from utils.runtime_paths import RuntimePaths, finalize_paths
    from utils import compute_pool
    private = {key: root/key for key in ('run_root', 'memory_root', 'artifact_root',
        'output_root', 'source_inbox_root', 'user_file_root', 'log_root')}
    paths = RuntimePaths(repository_root=runtime.parent, runtime_root=runtime,
        system_root=runtime.parent/'system', workspace_root=runtime.parent/'workspace', **private)
    bindings = root/'bindings.json'
    write_json(bindings, {'schema':'atr.path_bindings.v1', 'stores':private})
    os.environ['ATR_PATH_BINDINGS'] = str(bindings)
    os.environ['ATR_LAYOUT_CONFIG'] = str(runtime/'configs/repository_layout.json')
    finalize_paths(paths)
    summary = {'hardware_predispatch_denied':False, 'real_llm':'not_attempted_offline',
               'parity':[], 'regressions':[], 'failures':[]}
    compute_pool.configure_compute_pool(1, paths=paths)
    try:
        for name in args.parity:
            case = root/name
            case.mkdir()
            try:
                summary['parity'].append(asyncio.run(parity(name, case, paths)))
                summary['hardware_predispatch_denied'] = True
                print(name + ': API/registered graph hashes and receipt reuse PASS', flush=True)
            except Exception as exc:
                failure = {'case':name, 'type':type(exc).__name__, 'error':str(exc)}
                summary['failures'].append(failure)
                print(json.dumps(failure), flush=True)
    finally:
        compute_pool.close_compute_pool()
    if not args.skip_regressions:
        suites = ['tests/unit/test_design_geometry_families.py',
                  'tests/unit/test_design_geometry_contract.py',
                  'tests/unit/test_design_geometry_legacy.py',
                  'tests/unit/test_serial_catalog_profiles.py', 'tests/unit/test_serial_distribution.py',
                  'tests/unit/test_workspace_catalog.py', 'tests/unit/test_serial_protocols.py']
        command = [sys.executable, '-m', 'pytest', *suites, '-q', '--tb=short',
                   '--basetemp', str(root/'numerical-tests'), '--junitxml', str(root/'regressions.xml')]
        with (root/'regressions.log').open('w') as log:
            try:
                run = subprocess.run(command, cwd=runtime, stdout=log, stderr=subprocess.STDOUT,
                    env={**os.environ, 'PYTHONPATH':str(runtime)}, timeout=300)
                code = run.returncode
            except subprocess.TimeoutExpired:
                code = 124
        summary['regressions'].append({'command':command, 'returncode':code})
        if code:
            summary['failures'].append({'case':'regressions', 'returncode':code,
                                        'details':str(root/'regressions.log')})
        print('Regression exit: ' + str(code), flush=True)
    write_json(root/'summary.json', summary)
    return bool(summary['failures'])


if __name__ == '__main__':
    sys.exit(main())
