"""Settings/API → versioned Skill → registered HTTP tools → worker → evidence.

Only model HTTP and native desktop are synthetic; no device/service is started.
Mutations caught: bypassing verify, replaying actions on reload, dropping receipts,
shipping only source imports, or silently replacing legacy execution defaults.
"""
import hashlib
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from agents.equipment.agent import LabEquipmentAgent
from app import main
from device_bridges.windows_pyautogui.tools import register_equipment_tools
from mcp_tools.tool_registry import ToolRegistry
from orchestrator.state import Mode
from Pyautogui_server_for_window.bridge.computer_use_runtime import ComputerUseController
from tests.integration.test_equipment_profile_workspace_api import client
from tests.unit.test_equipment_agent import _state
from tests.unit.test_equipment_computer_use_runner import harness
from utils.equipment_skill_runtime import EquipmentSkillRegistry, canonical_sha256, validate_skill_package

FIXTURES = Path(__file__).parents[1] / 'fixtures/equipment_computer_use'


def setup_demo(tmp_path, monkeypatch, client, *, decisions=None, mode='computer_use', fault=None):
    assert (FIXTURES / 'computer_use_demo_v1.json').is_file(), 'synthetic versioned package fixture is missing'
    from tests.fixtures.equipment_computer_use.adapter import SyntheticDesktop
    source = json.loads((FIXTURES / 'computer_use_demo_v1.json').read_text())
    h = harness(tmp_path, monkeypatch, decisions)
    h.desktop = SyntheticDesktop(FIXTURES, tmp_path / 'synthetic-result.json')
    h.worker = ComputerUseController(tmp_path / 'worker', h.desktop, 'worker1')
    h.ctx.paths.memory_root = main.RUNTIME_PATHS.memory_root
    h.ctx.paths.memory_root.mkdir(parents=True, exist_ok=True)
    h.ctx.tools = ToolRegistry()
    bridge = register_equipment_tools(h.ctx.tools, {'devices': {'equipment': {'mode': 'live', 'windows_pyautogui': {
        'allow_live_execute': True, 'connection_memory_path': str(tmp_path / 'connections.json')}}}}, repo_root=tmp_path)
    bridge._write_connection_memory({'selected_candidate': 'worker1', 'candidates': {'worker1': {
        'bridge_url': 'http://worker.invalid', 'internal_key': 'synthetic-worker-secret', 'allow_live_execute': True}}})
    h.calls = []
    def transport(req):
        assert req.headers.get(bridge.config.token_header) == 'synthetic-worker-secret'
        if req.url.path == '/capabilities':
            return httpx.Response(200, json={'ok': True, 'computer_use_v1': True,
                'computer_use_limits': {'program_hash_binding': True}})
        payload = json.loads(req.content)
        operation = req.url.path.rsplit('/', 1)[-1]
        h.calls.append((operation, payload))
        if operation == 'execute':
            # Native legacy execution boundary, not a replacement tool handler.
            for action in ({'type': 'click', 'target_id': 'button'},
                           {'type': 'write', 'target_id': 'field', 'text': 'DEMO-001'},
                           {'type': 'click', 'target_id': 'submit'}):
                h.desktop.execute(action, {})
            return httpx.Response(200, json={'ok': True, 'status': 'completed', 'screen_checks': [{'ok': True}]})
        submit = operation == 'act' and payload['action'].get('target_id') == 'submit'
        if submit and fault == 'ambiguous':
            h.desktop.interrupt_after_effect = True
        result = h.worker.handle(operation, payload, 'synthetic-authenticated-principal')
        if submit and fault == 'lost_receipt':
            raise httpx.ReadTimeout('synthetic receipt lost after durable worker commit', request=req)
        return httpx.Response(200, json=result)
    real_client = httpx.Client
    monkeypatch.setattr(httpx, 'Client', lambda **kw: real_client(transport=httpx.MockTransport(transport), **kw))
    registry = EquipmentSkillRegistry(tmp_path / 'skills')
    package = registry.create_draft(recording=source['recording'], skill_id=source['skill_id'], version=source['version'],
        target_profile='windows_desktop_v1', model_snapshot={'provider': 'vllm', 'model': 'endpoint:selected'})
    workflow = package['workflow']
    workflow['computer_use'] = source['policy']
    registry.update_workflow(source['skill_id'], source['version'], workflow,
        expected_workflow_sha256=package['manifest']['workflow_sha256'])
    package = registry.compile(source['skill_id'], source['version'])
    registry.validate(source['skill_id'], source['version'])
    for program in package['programs']:
        bridge.config.registered_programs[program['program_id']] = program
    registry.mark_deployed(source['skill_id'], source['version'], bridge_id='worker1', deployment_sha256=canonical_sha256(package['programs']))
    validate_skill_package(registry.root / source['skill_id'] / source['version'])
    settings_path = main.RUNTIME_PATHS.memory_root / 'equipment_workspace_settings.json'
    monkeypatch.setattr(LabEquipmentAgent, '_WORKSPACE_SETTINGS_PATH', settings_path)
    if mode == 'computer_use':
        response = client.post('/api/equipment/profiles/windows_desktop_v1/settings', json={
            'execution_mode': mode, 'computer_use': {'max_turns': 4, 'request_timeout_s': 10, 'frame_max_age_s': 30}})
        assert response.status_code == 200, response.text
    state = _state(mode=Mode.LIVE, experiment_spec={'equipment_profile_id': 'windows_desktop_v1',
        'specimen_id': 'spec1', 'confirm_live_execute': True})
    request = {'skill_id': source['skill_id'], 'version': source['version'], 'target_profile': 'windows_desktop_v1',
        'registry_root': str(registry.root), 'sequence_id': 'sequence1', 'completion_scope': 'skill_step',
        'runtime_context': {'specimen_label': 'DEMO-001'}, 'skip_profile_vision_preflight': True}
    return h, registry, state, request


def click(prompt):
    return json.dumps({'schema': 'ax4lab.equipment_computer_use.decision.v1',
        'observation_id': prompt['observation']['observation_id'], 'kind': 'act', 'reason': 'synthetic demo button',
        'action': {'type': 'click', 'target_id': 'button', 'x': 1, 'y': 1}})


def write_value(prompt):
    value = json.loads(click(prompt))
    value['action'] = {'type': 'write', 'target_id': 'field', 'value_key': 'specimen_label'}
    return json.dumps(value)


def submit(prompt):
    value = json.loads(click(prompt))
    value['action'] = {'type': 'click', 'target_id': 'submit', 'x': 1, 'y': 3}
    return json.dumps(value)


@pytest.mark.asyncio
async def test_full_path_persists_verified_artifacts_and_reload_is_idempotent(tmp_path, monkeypatch, client):
    h, registry, state, request = setup_demo(tmp_path, monkeypatch, client, decisions=[click, write_value, submit, 'complete'])
    result = await LabEquipmentAgent()._run_equipment_skill(state, h.ctx, request)
    assert result.success, result.data
    assert json.loads(h.desktop.result_path.read_text()) == {'status': 'complete', 'source': 'synthetic', 'specimen': 'DEMO-001'}
    execution = result.data['equipment_skill_execution']
    assert execution['state'] == execution['runtime_execution']['lifecycle'] == 'COMPLETED'
    raw = result.data['equipment_result']
    assert raw['computer_use']['turns'] == 4
    records = [json.loads(Path(item['local_path']).read_text()) for item in raw['output_artifacts']]
    previous = ''
    for record in records:
        assert record['previous_sha256'] == previous
        previous = record.pop('sha256')
        assert hashlib.sha256(json.dumps(record, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode()).hexdigest() == previous
    assert {'intent', 'receipt', 'verification', 'release'} <= {r['kind'] for r in records}
    assert raw['screen_checks'][0]['evidence']['ok'] is True
    assert h.worker.state['lease'] is None
    assert len(h.prompts) == 4
    actions = [payload['action'] for op, payload in h.calls if op == 'act']
    assert actions == [{'type': 'click', 'target_id': 'button', 'x': 1, 'y': 1},
                       {'type': 'write', 'target_id': 'field', 'value_key': 'specimen_label'},
                       {'type': 'click', 'target_id': 'submit', 'x': 1, 'y': 3}]
    for payload, prompt in h.prompts:
        assert sum(part['type'] == 'image_url' for part in payload['messages'][-1]['content']) == 1
    # Fresh browser/API client and agent instance reuse the durable execution,
    # not a new action or a new completion based only on a model assertion.
    reloaded = TestClient(main.app).get('/api/equipment/profiles/windows_desktop_v1/state').json()
    assert reloaded['workspace_settings']['execution_mode'] == 'computer_use'
    before = len(h.calls)
    again = await LabEquipmentAgent()._run_equipment_skill(state, h.ctx, request)
    assert again.success and h.desktop.effects == 3
    assert len(h.calls) == before
    assert again.data['equipment_skill_execution']['execution_id'] == execution['execution_id']
    assert 'synthetic-worker-secret' not in json.dumps([result.data, records])
    assert 'endpoint-secret' not in json.dumps([result.data, records])


@pytest.mark.asyncio
async def test_model_complete_without_image_and_file_evidence_fails(tmp_path, monkeypatch, client):
    h, _, state, request = setup_demo(tmp_path, monkeypatch, client, decisions=['complete'])
    result = await LabEquipmentAgent()._run_equipment_skill(state, h.ctx, request)
    assert not result.success
    assert result.data['equipment_result']['failure_code'] == 'postcondition_failed'
    assert not h.desktop.result_path.exists() and h.desktop.effects == 0


@pytest.mark.asyncio
@pytest.mark.parametrize('fault', ['lost_receipt', 'ambiguous'])
async def test_interrupted_receipt_is_reconciled_without_replaying(tmp_path, monkeypatch, client, fault):
    h, _, state, request = setup_demo(tmp_path, monkeypatch, client, decisions=[click, write_value, submit, 'complete'], fault=fault)
    result = await LabEquipmentAgent()._run_equipment_skill(state, h.ctx, request)
    acts = [p for op, p in h.calls if op == 'act']
    assert len(acts) == h.desktop.effects == 3
    if fault == 'lost_receipt':
        assert result.success, result.data
        statuses = [p for op, p in h.calls if op == 'status']
        assert len(statuses) == 1 and statuses[0]['action_id'] == acts[-1]['action_id']
    else:
        assert not result.success
        assert result.data['equipment_result']['failure_code'] == 'action_requires_operator'
        assert h.worker.state['lease'] is not None
        # A settings rollback cannot turn an uncertain effect into a legacy retry.
        assert client.post('/api/equipment/profiles/windows_desktop_v1/settings', json={'execution_mode': 'skill_flow'}).status_code == 200
        again = await LabEquipmentAgent()._run_equipment_skill(state, h.ctx, request)
        assert not again.success
        assert again.data['equipment_handoff']['failure_code'] == 'resume_requires_operator'
        assert h.desktop.effects == 3


@pytest.mark.asyncio
async def test_same_package_retains_default_legacy_registered_execution(tmp_path, monkeypatch, client):
    h, _, state, request = setup_demo(tmp_path, monkeypatch, client, mode='skill_flow')
    result = await LabEquipmentAgent()._run_equipment_skill(state, h.ctx, request)
    assert result.success, result.data
    assert [op for op, _ in h.calls] == ['execute']
    assert h.desktop.effects == 3 and h.prompts == []
    assert 'computer_use' not in result.data['equipment_result']


@pytest.mark.asyncio
async def test_success_pixels_without_persisted_result_cannot_complete(tmp_path, monkeypatch, client):
    h, _, state, request = setup_demo(tmp_path, monkeypatch, client, decisions=[click, 'complete'])
    def discard_result(prompt):
        h.desktop.result_path.unlink()
        return 'complete'
    h.decisions[:] = [click, write_value, submit, discard_result]
    result = await LabEquipmentAgent()._run_equipment_skill(state, h.ctx, request)
    assert not result.success
    assert result.data['equipment_result']['failure_code'] == 'postcondition_failed'
    assert h.desktop.effects == 3


@pytest.mark.asyncio
async def test_real_flow_checkpoint_uses_verified_skill_result(tmp_path, monkeypatch, client):
    h, registry, state, _ = setup_demo(tmp_path, monkeypatch, client, decisions=[click, write_value, submit, 'complete'])
    state.current_experiment_spec['equipment_skill_registry_root'] = str(registry.root)
    flow = {'schema': 'atr.equipment_skill_flow.v1', 'flow_id': 'synthetic-flow', 'profile_id': 'windows_desktop_v1',
        'agentic_task_id': '', 'blocks': [{'id': 'demo', 'label': 'Synthetic demo',
            'skill': {'skill_id': 'computer_use_demo_v1', 'skill_version': '1.0.0'},
            'agentic': {'task': 'Produce the synthetic result', 'completed': '__complete__', 'failed': '__blocked__'},
            'vision': {'enabled': False}}]}
    checkpoint = {'run_context': {'specimen_label': 'DEMO-001'}}
    result = await LabEquipmentAgent()._run_equipment_skill_flow(state, h.ctx, flow, checkpoint=checkpoint)
    assert result.success, result.data
    assert checkpoint['execution_settings']['execution_mode'] == 'computer_use'
    assert checkpoint['execution_settings']['computer_use']['max_turns'] == 4
    assert checkpoint['computer_use_model_selection']['model'] == 'endpoint:selected'
    assert h.desktop.effects == 3 and h.worker.state['lease'] is None
