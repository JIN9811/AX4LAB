"""Resource boundary regressions; subprocesses are only inert test fixtures."""
from dataclasses import fields
import json
from pathlib import Path
import os
import subprocess
import sys

import pytest

from utils.runtime_paths import RuntimePaths
from utils.config_loader import load_all_configs
from device_bridges.camera_vision.specimen_pose_tracker import SpecimenPoseTrackerConfig, SpecimenPoseTrackerBridge
from device_bridges.lerobot.bridge import LeRobotBridgeConfig, LeRobotBridge


def paths_at(root):
    values = {f.name: root / f.name for f in fields(RuntimePaths)}
    values.update(repository_root=root, runtime_root=root / 'runtime', system_root=root / 'system')
    return RuntimePaths(**values)


def test_snapshot_setup_is_absolute_at_child_boundary(tmp_path):
    paths = paths_at(tmp_path)
    script = paths.runtime_root / 'scripts/vision/snapshot.sh'
    script.parent.mkdir(parents=True)
    script.write_text('#!/usr/bin/env python3\nimport os,json\nprint(json.dumps({"ok":True,"pose":{"setup":os.environ["ATR_SPECIMEN_POSE_EXTRA_SETUP_PATHS"]}}))\n')
    script.chmod(0o755)
    setup = paths.runtime_root / 'ros/install/setup.bash'
    setup.parent.mkdir(parents=True)
    setup.touch()
    config = SpecimenPoseTrackerConfig.from_devices_config({'specimen_pose_tracker': {
        'script_path': str(script), 'ros_setup_paths': [], 'extra_setup_paths': ['ros/install/setup.bash'],
        'rsusb_pythonpath': 'native/Release', 'rsusb_library_path': 'native/lib'}}, repo_root=tmp_path, paths=paths)
    assert config.rsusb_pythonpath == str(tmp_path / 'runtime/native/Release')
    assert config.rsusb_library_path == str(tmp_path / 'runtime/native/lib')
    result = SpecimenPoseTrackerBridge(config).snapshot({'mode':'live'})
    assert result['pose']['setup'] == str(setup)


def test_missing_snapshot_setup_does_not_launch(tmp_path):
    marker = tmp_path / 'spawned'
    script = tmp_path / 'snapshot.sh'
    script.write_text(f'#!/bin/sh\ntouch "{marker}"\n')
    script.chmod(0o755)
    config = SpecimenPoseTrackerConfig(script_path=script, log_dir=tmp_path / 'logs', ros_setup_paths=[str(tmp_path / 'missing')])
    result = SpecimenPoseTrackerBridge(config).snapshot({'mode':'live'})
    assert result['failure_code'] == 'SPECIMEN_POSE_SETUP_NOT_FOUND'
    assert not marker.exists()


def test_tracked_defaults_allow_profile_resources(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[3]
    paths = paths_at(root)
    profile = tmp_path / 'profile.json'
    profile.write_text(json.dumps({'schema':'atr.installation.v1','resources':{
        'utm': {'workspace_root':'utm', 'script_path':'utm/run.sh', 'ros_setup_paths':['ros/setup.bash']},
        'lerobot': {'conda_executable':'custom/bin/conda', 'conda_env_name':'custom-env', 'pi05_repo_root':'rtc'},
        'realsense': {'native_python_path':'rsusb'}}}))
    monkeypatch.setenv('ATR_INSTALL_PROFILE', str(profile))
    cfg = load_all_configs(root / 'runtime/configs', paths=paths)
    assert cfg['devices']['devices']['utm_vision_runtime']['workspace_root'] == str(tmp_path / 'utm')
    assert cfg['devices']['devices']['utm_vision_runtime']['ros_setup_paths'] == [str(tmp_path / 'ros/setup.bash')]
    assert cfg['lerobot']['lerobot']['conda_env_name'] == 'custom-env'
    assert cfg['devices']['devices']['specimen_pose_tracker']['rsusb_pythonpath'] == str(tmp_path / 'rsusb')


def test_isaac_defaults_owned_by_backend_and_explicit_overrides_win(tmp_path):
    paths = paths_at(tmp_path)
    config = LeRobotBridgeConfig.from_config({}, paths=paths)
    bridge = LeRobotBridge(config)
    assert bridge.isaac_resource_defaults()['stage_path'] == str(tmp_path / 'runtime/sim/robotis_omx/scene/omx_table_layout_20260915.usda')
    config = LeRobotBridgeConfig.from_config({'isaac_scene_path':'/chosen/scene.usda', 'isaac_lab_path':'/chosen/lab', 'isaac_sim_python':'/chosen/python.sh'}, paths=paths)
    assert LeRobotBridge(config).isaac_resource_defaults() == {'stage_path':'/chosen/scene.usda', 'isaac_lab_path':'/chosen/lab', 'isaac_sim_python':'/chosen/python.sh'}


def test_rtc_environment_uses_configured_source_and_preserves_override(tmp_path, monkeypatch):
    config = LeRobotBridgeConfig.from_config({'pi05_repo_root':'external rtc'}, repo_root=tmp_path)
    bridge = LeRobotBridge(config)
    expected = str(tmp_path / 'external rtc/examples/rtc/eval_with_real_robot.py')
    assert bridge._source_environment()['ATR_LEROBOT_RTC_SCRIPT'] == expected
    assert bridge._source_environment()['ATR_PI05_RTC_SCRIPT'] == expected
    monkeypatch.setenv('ATR_LEROBOT_RTC_SCRIPT', '/custom/rtc.py')
    assert bridge._source_environment()['ATR_LEROBOT_RTC_SCRIPT'] == '/custom/rtc.py'


def test_conda_module_probe_uses_configured_executable(tmp_path):
    conda = tmp_path / 'custom conda'
    conda.write_text('#!/bin/sh\n[ "$1 $2 $3 $4 $5" = "run --no-capture-output -n portable python" ]\n')
    conda.chmod(0o755)
    bridge = LeRobotBridge(LeRobotBridgeConfig.from_config({'conda_executable':str(conda)}, repo_root=tmp_path))
    assert bridge._conda_env_has_module('portable', 'json') is True


def test_observer_missing_setup_fails_before_ros(tmp_path):
    from device_bridges.camera_vision.utm_state_observer import read_compression_tester_summary_once
    with pytest.raises(FileNotFoundError, match='ROS setup'):
        read_compression_tester_summary_once(ros_setup_paths=[str(tmp_path / 'missing')])


def test_utm_absent_resources_are_unconfigured(tmp_path):
    from device_bridges.camera_vision.utm_runtime_bridge import UTMRuntimeConfig, UTMRuntimeProcessManager
    manager = UTMRuntimeProcessManager(UTMRuntimeConfig.from_devices_config({}, repo_root=tmp_path))
    assert manager.status()['status'] == 'not_configured'
    assert manager.start()['failure_code'] == 'UTM_RUNTIME_NOT_CONFIGURED'


def test_missing_live_conda_does_not_fall_back_to_server_python(tmp_path):
    from device_bridges.lerobot.bridge import IsaacLabSyntheticRequest
    bridge = LeRobotBridge(LeRobotBridgeConfig.from_config({'conda_executable':'/not-installed/conda'}, repo_root=tmp_path))
    with pytest.raises(ValueError, match='conda_executable'):
        bridge._isaac_lab_live_e2e_command(IsaacLabSyntheticRequest())


def test_conda_e2e_command_identifies_runner_script_for_preflight(tmp_path):
    from device_bridges.lerobot.bridge import IsaacLabSyntheticRequest, _command_script_path
    bridge = LeRobotBridge(LeRobotBridgeConfig.from_config({'conda_executable':'/bin/true',
        'isaac_lab_path':'/configured/lab', 'isaac_sim_python':'/configured/python.sh'}, repo_root=tmp_path))
    command = bridge._isaac_lab_live_e2e_command(IsaacLabSyntheticRequest())
    assert _command_script_path(command) == tmp_path / 'scripts/lerobot_isaac_lab_e2e_smoke.py'


def test_standalone_devices_loader_applies_profile_but_preserves_override(tmp_path, monkeypatch):
    from scripts.lab_equipment_live_utm_validation import load_devices_config
    profile = tmp_path / 'profile.json'
    profile.write_text(json.dumps({'schema':'atr.installation.v1','resources':{'utm':{'workspace_root':'external'}}}))
    monkeypatch.setenv('ATR_INSTALL_PROFILE', str(profile))
    source = tmp_path / 'devices.yaml'
    source.write_text('devices:\n  utm_vision_runtime:\n    workspace_root: ""\n')
    assert load_devices_config(source, paths=paths_at(tmp_path))['devices']['utm_vision_runtime']['workspace_root'] == str(tmp_path / 'external')
    source.write_text('devices:\n  utm_vision_runtime:\n    workspace_root: /operator/utm\n')
    assert load_devices_config(source, paths=paths_at(tmp_path))['devices']['utm_vision_runtime']['workspace_root'] == '/operator/utm'


def test_rtc_wrapper_requires_explicit_source(monkeypatch):
    from scripts.lerobot_live_rollout_wrapper import _lerobot_rtc_main
    monkeypatch.delenv('ATR_LEROBOT_RTC_SCRIPT', raising=False)
    with pytest.raises(ValueError, match='ATR_LEROBOT_RTC_SCRIPT'):
        _lerobot_rtc_main()


def test_nemoclaw_missing_proxy_is_configuration_error(tmp_path):
    from backends.nemoclaw_client import NemoClawBackend
    backend = NemoClawBackend(proxy_script='')
    with pytest.raises(RuntimeError, match='NEMOCLAW_PROXY_SCRIPT'):
        backend._start_proxy_if_needed('test-only-placeholder')


def test_isaac_utility_resolves_profile_and_preserves_cli(tmp_path, monkeypatch):
    from scripts.lerobot_isaac_lab_robomimic_train import _isaac_lab_path
    profile = tmp_path / 'profile.json'
    profile.write_text(json.dumps({'schema':'atr.installation.v1','resources':{'isaac':{'lab_root':'lab folder'}}}))
    monkeypatch.setenv('ATR_INSTALL_PROFILE', str(profile))
    assert _isaac_lab_path([]) == tmp_path / 'lab folder'
    argv = ['--isaac-lab-path', '/operator/lab', '--task', 'unchanged']
    assert _isaac_lab_path(argv) == Path('/operator/lab')
    assert argv == ['--task', 'unchanged']


def test_pipeline_never_rediscovers_home_install(tmp_path, monkeypatch):
    from device_bridges.isaac_lab_synthetic import IsaacLabSyntheticPipeline
    from device_bridges.lerobot.bridge import IsaacLabSyntheticRequest
    monkeypatch.setenv('HOME', str(tmp_path))
    (tmp_path / 'IsaacLab').mkdir()
    (tmp_path / 'IsaacSim').mkdir()
    (tmp_path / 'IsaacSim/python.sh').touch()
    pipeline = IsaacLabSyntheticPipeline(repo_root=tmp_path, allowed_roots=[tmp_path])
    request = IsaacLabSyntheticRequest()
    assert pipeline._isaac_lab_path(request) is None
    assert pipeline._isaac_sim_python_value(request) == ''
    assert pipeline._check_runtime(request).status == 'blocked'
    assert pipeline._compatibility_summary(request)['isaac_lab_exists'] is False


def test_gui_template_uses_backend_resource_values(tmp_path):
    from html.parser import HTMLParser
    from jinja2 import Environment, FileSystemLoader
    class Inputs(HTMLParser):
        def __init__(self):
            super().__init__()
            self.values = {}
        def handle_starttag(self, tag, attrs):
            attrs = dict(attrs)
            if tag == 'input':
                self.values[attrs.get('id')] = attrs.get('value')
    env = Environment(loader=FileSystemLoader(Path(__file__).resolve().parents[2] / 'web/templates'), autoescape=True)
    resources = {'isaac_lab_path':'/operator/lab & tools','isaac_sim_python':'/operator/python.sh','stage_path':str(tmp_path / 'runtime/scene.usda')}
    rendered = env.get_template('lerobot.html').render(isaac_resources=resources)
    inputs = Inputs()
    inputs.feed(rendered)
    assert inputs.values['isaac-synthetic-isaac-lab-path'] == '/operator/lab & tools'
    assert inputs.values['isaac-synthetic-isaac-sim-python'] == '/operator/python.sh'
    assert inputs.values['isaac-synthetic-stage-path'] == str(tmp_path / 'runtime/scene.usda')


@pytest.mark.parametrize('mode,key,code', [
    ('isaac_extension', 'isaac_mirror_receiver_isaac_sim_executable', 'LEROBOT_ISAAC_SIM_EXECUTABLE_NOT_FOUND'),
    ('python_script', 'isaac_mirror_receiver_python', 'LEROBOT_ISAAC_MIRROR_RECEIVER_PYTHON_NOT_FOUND'),
])
@pytest.mark.parametrize('selection', ['', 'directory', 'nonexecutable', 'missing'])
def test_mirror_command_rejects_unusable_executable(tmp_path, monkeypatch, mode, key, code, selection):
    for name in ['ATR_ISAAC_SIM_EXECUTABLE', 'ATR_ISAAC_MIRROR_RECEIVER_PYTHON']:
        monkeypatch.delenv(name, raising=False)
    root = Path(__file__).resolve().parents[3]
    bridge = LeRobotBridge(LeRobotBridgeConfig.from_config({}, paths=paths_at(root)))
    candidate = tmp_path / selection if selection else None
    if selection == 'directory':
        candidate.mkdir()
    elif selection == 'nonexecutable':
        candidate.write_text('#!/bin/sh\nexit 0\n')
        candidate.chmod(0o644)
    result = bridge._isaac_mirror_receiver_command({
        'isaac_mirror_receiver_launch_mode':mode, key:str(candidate) if candidate else '',
    }, 'http://127.0.0.1:8766/joints')
    assert result['ok'] is False
    assert result['failure_code'] == code
    assert 'command' not in result


@pytest.mark.parametrize('mode,key', [
    ('isaac_extension', 'isaac_mirror_receiver_isaac_sim_executable'),
    ('python_script', 'isaac_mirror_receiver_python'),
])
@pytest.mark.parametrize('use_path', [False, True])
def test_mirror_command_accepts_executable_file_or_path_command(tmp_path, monkeypatch, mode, key, use_path):
    executable = tmp_path / 'portable-runtime'
    executable.write_text('#!/bin/sh\nexit 0\n')
    executable.chmod(0o755)
    monkeypatch.setenv('PATH', str(tmp_path))
    root = Path(__file__).resolve().parents[3]
    bridge = LeRobotBridge(LeRobotBridgeConfig.from_config({}, paths=paths_at(root)))
    result = bridge._isaac_mirror_receiver_command({
        'isaac_mirror_receiver_launch_mode':mode, key:executable.name if use_path else str(executable),
    }, 'http://127.0.0.1:8766/joints')
    assert result['ok'] is True
    assert result['command'][0] == str(executable)


def test_unconfigured_e2e_smoke_returns_resource_blocker_without_fixture(tmp_path):
    bridge = LeRobotBridge(LeRobotBridgeConfig.from_config({}, repo_root=tmp_path))
    dataset = tmp_path / 'artifacts/missing-resource-fixture'
    result = bridge.isaac_lab_run_e2e_smoke({'dataset_path':str(dataset), 'e2e_create_fixture':True})
    assert result['ok'] is False
    assert result['status'] == 'BLOCKED'
    assert result['error']['code'] == 'ISAAC_LAB_E2E_RESOURCE_NOT_CONFIGURED'
    assert result['tool'] == 'lerobot.isaac_lab.e2e_smoke'
    assert result['schema'] == 'atr.lerobot.synthetic_e2e.smoke_report.v1'
    assert not dataset.exists()


@pytest.mark.parametrize('mode,key', [
    ('isaac_extension', 'isaac_mirror_receiver_isaac_sim_executable'),
    ('python_script', 'isaac_mirror_receiver_python'),
])
@pytest.mark.parametrize('use_path', [False, True])
def test_mirror_command_preserves_selected_executable_symlink(tmp_path, monkeypatch, mode, key, use_path):
    target = tmp_path / 'system-runtime'
    target.write_text('#!/bin/sh\nexit 0\n')
    target.chmod(0o755)
    selected = tmp_path / 'environment/bin/python'
    selected.parent.mkdir(parents=True)
    selected.symlink_to(target)
    monkeypatch.setenv('PATH', str(selected.parent))
    root = Path(__file__).resolve().parents[3]
    bridge = LeRobotBridge(LeRobotBridgeConfig.from_config({}, paths=paths_at(root)))
    result = bridge._isaac_mirror_receiver_command({
        'isaac_mirror_receiver_launch_mode':mode, key:selected.name if use_path else str(selected),
    }, 'http://127.0.0.1:8766/joints')
    assert result['ok'] is True
    assert result['command'][0] == str(selected)
    assert result['command'][0] != str(target)


@pytest.mark.parametrize('selection', ['profile', 'legacy', 'request'])
def test_profile_to_config_to_command_preserves_environment_symlink(tmp_path, selection):
    from device_bridges.lerobot.bridge import IsaacLabSyntheticRequest
    root = Path(__file__).resolve().parents[3]
    paths = paths_at(root)
    selected = tmp_path / 'selected environment/bin/python'
    selected.parent.mkdir(parents=True)
    selected.symlink_to(sys.executable)
    other = tmp_path / 'other environment/bin/python'
    other.parent.mkdir(parents=True)
    other.symlink_to(sys.executable)
    for executable in (selected, other):
        (executable.parent.parent / 'pyvenv.cfg').write_text(
            'home = /usr/bin\ninclude-system-site-packages = false\n')
    profile = tmp_path / 'profile.json'
    profile.write_text(json.dumps({'schema': 'atr.installation.v1', 'resources': {
        'isaac': {'sim_python': str(selected), 'lab_root': 'lab'},
        'lerobot': {'conda_executable': str(selected)}}}))
    configs = tmp_path / 'configs'
    configs.mkdir()
    (configs / 'lerobot.yaml').write_text(
        'lerobot: ' + json.dumps({'isaac_sim_python': str(other)} if selection == 'legacy' else {}) + '\n')
    bundle = load_all_configs(configs, paths=paths, environ={'ATR_INSTALL_PROFILE': str(profile)})
    bridge = LeRobotBridge(LeRobotBridgeConfig.from_config(bundle['lerobot'], paths=paths))
    expected = other if selection in {'legacy', 'request'} else selected
    request = IsaacLabSyntheticRequest(isaac_sim_python=str(other) if selection == 'request' else '')
    command = bridge._isaac_lab_live_e2e_command(request)
    assert command[0] == str(selected)  # Conda executable alias is also retained.
    assert command[command.index('--isaac-sim-python') + 1] == str(expected)
    mirror = bridge._isaac_mirror_receiver_command({
        'isaac_mirror_receiver_launch_mode': 'python_script',
        **({'isaac_mirror_receiver_python': str(other)} if selection == 'request' else {}),
    }, 'http://127.0.0.1:8766/joints')
    assert mirror['ok'] is True
    assert mirror['command'][0] == str(expected)
    probe = subprocess.run([mirror['command'][0], '-c', 'import sys; print(sys.prefix)'],
                           capture_output=True, text=True, check=True)
    assert probe.stdout.strip() == str(expected.parent.parent)


@pytest.mark.parametrize('final_override', ['none', 'relative', 'home'])
def test_rtc_launch_normalizes_both_selectors_with_legacy_child_base(tmp_path, monkeypatch, final_override):
    paths = paths_at(tmp_path / 'checkout with spaces')
    paths.runtime_root.mkdir(parents=True)
    parent = tmp_path / 'unrelated caller'
    parent.mkdir()
    monkeypatch.chdir(parent)
    names = ('ATR_LEROBOT_RTC_SCRIPT', 'ATR_PI05_RTC_SCRIPT')
    for name in names:
        monkeypatch.setenv(name, 'operator scripts/inherited.py')
    bridge = LeRobotBridge(LeRobotBridgeConfig.from_config(
        {'pi05_repo_root': 'profile rtc'}, repo_root=paths.runtime_root))
    observed = tmp_path / 'child.json'
    code = ('import json,os,pathlib; pathlib.Path(' + repr(str(observed)) + ').write_text(json.dumps('
            '{"cwd":os.getcwd(), "values":[os.environ[n] for n in ' + repr(names) + ']}))')
    overrides = {name: 'final scripts/override.py' for name in names} if final_override != 'none' else {}
    if final_override == 'home':
        overrides = {'HOME': str(tmp_path / 'child home'), **{name: '~/rtc.py' for name in names}}
    result = bridge._start_live_process(session_id='rtc', command=[sys.executable, '-c', code], env_overrides=overrides)
    assert result['ok'] is True, result
    child = json.loads(observed.read_text())
    relative = 'final scripts/override.py' if final_override != 'none' else 'operator scripts/inherited.py'
    expected = tmp_path / 'child home/rtc.py' if final_override == 'home' else paths.runtime_root / relative
    assert child == {'cwd': str(paths.runtime_root), 'values': [str(expected)] * 2}
    assert os.getcwd() == str(parent)


def test_e2e_cli_keeps_relative_selected_python_symlink(tmp_path, monkeypatch, capsys):
    from scripts import lerobot_isaac_lab_e2e_smoke as smoke
    from types import SimpleNamespace
    selected = tmp_path / 'operator environment/bin/python'
    selected.parent.mkdir(parents=True)
    selected.symlink_to(sys.executable)
    monkeypatch.chdir(tmp_path)
    # Keep CLI parsing/path normalization real; stop at the expensive pipeline boundary.
    monkeypatch.setattr(smoke, '_bridge', lambda *args, **kwargs: SimpleNamespace(
        isaac_resource_defaults=lambda: {'isaac_lab_path': '/profile/lab', 'isaac_sim_python': '/profile/python'},
        isaac_lab_run_e2e=lambda payload: {'ok': True, 'selected': payload['isaac_sim_python']}))
    assert smoke.main(['--repo-root', str(tmp_path), '--dataset-path', 'unused',
                       '--isaac-sim-python', 'operator environment/bin/python']) == 0
    assert json.loads(capsys.readouterr().out)['selected'] == str(selected)


def test_pipeline_worker_python_value_keeps_environment_symlink(tmp_path, monkeypatch):
    from device_bridges.isaac_lab_synthetic import IsaacLabSyntheticPipeline
    from device_bridges.lerobot.bridge import IsaacLabSyntheticRequest
    selected = tmp_path / 'operator environment/bin/python'
    selected.parent.mkdir(parents=True)
    selected.symlink_to(sys.executable)
    monkeypatch.chdir(tmp_path)
    pipeline = IsaacLabSyntheticPipeline(repo_root=tmp_path, allowed_roots=[tmp_path])
    request = IsaacLabSyntheticRequest(isaac_sim_python='operator environment/bin/python')
    assert pipeline._isaac_sim_python_value(request) == str(selected)


@pytest.mark.parametrize('base', ['runtime', 'external lab', 'post-run job'])
def test_rtc_environment_preserves_each_explicit_child_cwd(tmp_path, monkeypatch, base):
    bridge = LeRobotBridge(LeRobotBridgeConfig.from_config({}, repo_root=tmp_path / 'runtime'))
    for key in ('ATR_LEROBOT_RTC_SCRIPT', 'ATR_PI05_RTC_SCRIPT'):
        monkeypatch.setenv(key, 'operator scripts/rtc.py')
    selected_cwd = tmp_path / base
    env = bridge._source_environment(cwd=selected_cwd)
    for key in ('ATR_LEROBOT_RTC_SCRIPT', 'ATR_PI05_RTC_SCRIPT'):
        assert env[key] == str(selected_cwd / 'operator scripts/rtc.py')
