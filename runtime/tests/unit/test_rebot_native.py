import copy
import json
import signal
import sys
from pathlib import Path

import pytest

from device_bridges.lerobot import rebot_native as native
from device_bridges.lerobot_bridge import LeRobotBridge, LeRobotBridgeConfig


@pytest.fixture
def bridge(tmp_path):
    import yaml
    config = yaml.safe_load((Path(__file__).parents[2] / 'configs/lerobot.yaml').read_text())
    return LeRobotBridge(LeRobotBridgeConfig.from_config(config, repo_root=tmp_path))


def settings(quest=False):
    robot = {'type': 'rebot_vr', 'id': 'bi_follower_vr'} if quest else {
        'type': 'bi_rebot_b601_follower', 'id': 'bi_follower',
        'left_arm_config': {'motor_family': 'rs', 'can_adapter': 'socketcan', 'port': 'can1'},
        'right_arm_config': {'motor_family': 'rs', 'can_adapter': 'socketcan', 'port': 'can0'},
    }
    return {'python': sys.executable, 'config': {'robot': robot, 'teleop':
        {'type': 'quest3', 'id': 'quest3'} if quest else {
            'type': 'bi_rebot_102_leader', 'id': 'bi_leader',
            'left_arm_config': {'port': '/dev/left'}, 'right_arm_config': {'port': '/dev/right'}},
        'fps': 30, 'display_data': False}}


@pytest.mark.parametrize('quest', [False, True])
def test_native_settings_roundtrip_and_cli_preserve_config(bridge, quest):
    pid = 'rebot_b601_rs_quest' if quest else 'rebot_b601_rs'
    value = settings(quest)
    native.save_settings(bridge, pid, value)
    assert native.load_settings(bridge, pid) == value
    command = native.command(bridge, pid, 'teleoperate', {'fps': 30, 'display_data': True})
    assert command[:2] == [sys.executable, '-u']
    assert command[2].endswith('/scripts/rebot_native_runner.py')
    assert command[3] == 'teleoperate'
    assert '--fps=30' in command
    assert '--display_data=true' in command
    assert not any(a.startswith(('--robot.port=', '--teleop.port=')) for a in command)
    assert '--robot.type=' + value['config']['robot']['type'] in command
    assert native.load_settings(bridge, pid) == value


def test_record_maps_dataset_and_ignores_omx_options(bridge):
    native.save_settings(bridge, 'rebot_b601_rs_quest', settings(True))
    cmd = native.command(bridge, 'rebot_b601_rs_quest', 'record', {
        'fps': 30, 'dataset_repo_id': 'lab/demo', 'dataset_path': '/tmp/data/demo',
        'episode_s': 60, 'reset_s': 5, 'num_episodes': 3, 'push_to_hub': False,
        'active_robot_cam_enabled': True, 'rollout_linear_enabled': True,
    })
    assert '--dataset.repo_id=lab/demo' in cmd
    assert '--dataset.root=/tmp/data/demo' in cmd
    assert '--dataset.fps=30' in cmd
    assert not any('omx' in a or 'wrapper' in a for a in cmd)


def test_record_default_repo_uses_its_own_dataset_directory(bridge):
    native.save_settings(bridge, 'rebot_b601_rs', settings())
    command = native.command(bridge, 'rebot_b601_rs', 'record', {'mode': 'live'})
    assert '--dataset.root=' + str(bridge.config.dataset_root / 'local/rebot') in command


def test_invalid_types_do_not_overwrite_saved_settings(bridge):
    original = settings()
    native.save_settings(bridge, 'rebot_b601_rs', original)
    invalid = copy.deepcopy(original)
    invalid['config']['robot']['type'] = 'omx_follower'
    with pytest.raises(ValueError):
        native.save_settings(bridge, 'rebot_b601_rs', invalid)
    assert native.load_settings(bridge, 'rebot_b601_rs') == original


def test_quest_rollout_is_rejected_before_process_launch(bridge):
    with pytest.raises(ValueError, match='teleoperate.*record'):
        native.command(bridge, 'rebot_b601_rs_quest', 'rollout', {})


def test_native_environment_does_not_inherit_omx_source_or_hooks(monkeypatch):
    monkeypatch.setenv('PYTHONPATH', '/omx/src:/ax4lab/runtime')
    monkeypatch.setenv('ATR_LEROBOT_RAW_DEPTH_ADAPTER', '1')
    monkeypatch.setenv('DISPLAY', ':0')
    env = native.environment()
    assert 'PYTHONPATH' not in env
    assert 'ATR_LEROBOT_RAW_DEPTH_ADAPTER' not in env
    assert env['DISPLAY'] == ':0'


def test_unknown_stop_does_not_fall_back_to_another_profile(bridge):
    bridge._sessions['omx'] = {'session_id': 'omx', 'profile_id': 'robotis_omx_ai', 'workflow': 'teleoperate', 'status': 'TELEOP_ACTIVE'}
    result = native.stop(bridge, 'teleoperate', {'profile_id': 'rebot_b601_rs', 'session_id': 'missing'})
    assert result['ok'] is False
    assert bridge._sessions['omx']['status'] == 'TELEOP_ACTIVE'


def test_existing_bridge_api_dispatches_native_preview(bridge):
    native.save_settings(bridge, 'rebot_b601_rs_quest', settings(True))
    result = bridge.teleoperate_start({'profile_id': 'rebot_b601_rs_quest', 'mode': 'test', 'fps': 30})
    assert result['status'] == 'PREVIEW'
    assert result['actuation_performed'] is False
    assert result['command_preview'][0] == sys.executable


def test_record_stop_never_runs_global_cleanup(bridge, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Must not clean up unrelated robot processes')
    monkeypatch.setattr(bridge, '_cleanup_lerobot_processes', forbidden)
    monkeypatch.setattr(bridge, 'cleanup_all_lerobot_processes', forbidden)
    result = bridge.record_control({'profile_id': 'rebot_b601_rs', 'session_id': 'missing', 'mode': 'live', 'action': 'stop'})
    assert result['ok'] is False


def test_scoped_stop_signals_cli_once_and_waits_for_cleanup(bridge):
    class Process:
        pid = 456
        signals = []
        def poll(self): return None
        def send_signal(self, sig): self.signals.append(sig)
    process = Process()
    bridge._processes['native'] = process
    bridge._sessions['native'] = {'session_id': 'native', 'profile_id': 'rebot_b601_rs_quest', 'workflow': 'record', 'status': 'RUNNING'}
    payload = {'profile_id': 'rebot_b601_rs_quest', 'session_id': 'native', 'action': 'stop'}
    assert native.control(bridge, payload)['status'] == 'STOPPING'
    assert native.control(bridge, payload)['status'] == 'STOPPING'
    assert process.signals == [signal.SIGINT]


def test_nested_motor_maps_remain_json_arguments(bridge):
    cfg = settings()
    cfg['config']['robot']['left_arm_config']['mit_kp'] = {'joint_1': 5}
    native.save_settings(bridge, 'rebot_b601_rs', cfg)
    cmd = native.command(bridge, 'rebot_b601_rs', 'teleoperate', {})
    assert '--robot.left_arm_config.mit_kp={"joint_1":5}' in cmd


def test_runtime_fps_override_is_validated(bridge):
    native.save_settings(bridge, 'rebot_b601_rs', settings())
    with pytest.raises(ValueError, match='FPS'):
        native.command(bridge, 'rebot_b601_rs', 'teleoperate', {'fps': -100})


def test_session_id_only_status_resolves_native_profile(bridge):
    bridge._sessions['native'] = {'session_id': 'native', 'profile_id': 'rebot_b601_rs', 'workflow': 'teleoperate', 'status': 'RUNNING', 'native_rebot': True}
    assert native.selected(bridge, {'session_id': 'native'})
    assert native.status(bridge, 'teleoperate', {'session_id': 'native'})['session_id'] == 'native'


def test_console_entrypoint_owner_is_detected():
    assert native.is_external_owner([b'/env/bin/python', b'/env/bin/lerobot-teleoperate'])
    assert not native.is_external_owner([b'python', b'-c', b'print("lerobot-teleoperate")'])


def test_runner_cleans_up_when_connect_is_interrupted(capsys):
    from scripts import rebot_native_runner as runner
    from types import SimpleNamespace
    class Device:
        is_connected = True
        def disconnect(self): self.is_connected = False
    leader = Device()
    robot = Device()
    module = SimpleNamespace(make_robot_from_config=lambda _: robot,
                             make_teleoperator_from_config=lambda _: leader)
    def main():
        module.make_teleoperator_from_config(None)
        module.make_robot_from_config(None)
        raise KeyboardInterrupt()
    module.main = main
    runner.run(module)
    assert not robot.is_connected and not leader.is_connected
    assert 'AX4LAB_REBOT_CLEANUP_OK' in capsys.readouterr().out


def test_terminal_control_writes_only_session_pty(bridge, tmp_path):
    import os
    import pty
    import tty
    master, slave = pty.openpty()
    tty.setraw(slave)
    log = tmp_path / 'native.log'
    log.write_text('Using terminal keyboard input\nRecording episode 0\n')
    class Process:
        def poll(self): return None
    bridge._processes['native'] = Process()
    bridge._sessions['native'] = {'session_id': 'native', 'profile_id': 'rebot_b601_rs', 'workflow': 'record', 'status': 'RUNNING', 'log_path': str(log)}
    bridge._native_input_fds['native'] = master
    try:
        result = native.control(bridge, {'profile_id': 'rebot_b601_rs', 'session_id': 'native', 'action': 'next'})
        assert result['control']['status'] == 'submitted'
        assert os.read(slave, 3) == b'\x1b[C'
    finally:
        os.close(master)
        os.close(slave)


def test_exit_without_cleanup_evidence_is_not_reported_success(bridge):
    class Process:
        def poll(self): return 0
    bridge._processes['native'] = Process()
    result = native.response(bridge, {'session_id': 'native', 'status': 'RUNNING'})
    assert result['status'] == 'FAILED'
    assert result['cleanup_verified'] is False


def test_cleanup_accepts_disconnected_leader_bus():
    from scripts.rebot_native_runner import cleanup
    from types import SimpleNamespace
    cleanup([SimpleNamespace(is_connected=False, bus=SimpleNamespace(is_connected=False))])


def test_legacy_cleanup_excludes_native_process_tree(bridge, monkeypatch):
    from types import SimpleNamespace
    bridge._sessions['n'] = {'session_id': 'n', 'native_rebot': True}
    bridge._processes['n'] = SimpleNamespace(pid=90001, poll=lambda: None)
    monkeypatch.setattr(bridge, '_project_lerobot_pids', lambda _: [90001])
    monkeypatch.setattr(bridge, '_lerobot_display_viewer_pids', lambda _: [90002])
    monkeypatch.setattr(bridge, '_expand_descendant_pids', lambda roots: [90001, 90002] if roots else [])
    monkeypatch.setattr('os.getpgid', lambda pid: pid)
    monkeypatch.setattr('os.kill', lambda *args: pytest.fail('Native owner must not be killed by legacy cleanup'))
    assert bridge._cleanup_lerobot_processes('record') == []


@pytest.mark.parametrize('method', ['rollout_stop', 'replay_stop', 'train_cancel'])
def test_native_unsupported_stop_cannot_reset_other_sessions(bridge, monkeypatch, method):
    monkeypatch.setattr(bridge, '_stop_session', lambda *a, **k: pytest.fail('Generic stop called'))
    monkeypatch.setattr(bridge, '_stop_all_workflow_sessions', lambda *a, **k: pytest.fail('Generic reset called'))
    assert getattr(bridge, method)({'profile_id': 'rebot_b601_rs'})['status'] == 'IDLE'


def test_live_start_requires_confirmation_before_parser_or_hardware(bridge, monkeypatch):
    native.save_settings(bridge, 'rebot_b601_rs', settings())
    monkeypatch.setattr(native, 'validate', lambda *a, **k: pytest.fail('Must require confirmation first'))
    result = bridge.teleoperate_start({'profile_id': 'rebot_b601_rs', 'mode': 'live', 'confirm_live_execute': False})
    assert not result['ok']
    assert 'Confirm live' in result['message']


@pytest.mark.parametrize('quest', [False, True])
def test_gui_record_start_owns_process_and_pty_only(bridge, monkeypatch, quest):
    import os
    pid = 'rebot_b601_rs_quest' if quest else 'rebot_b601_rs'
    native.save_settings(bridge, pid, settings(quest))
    launched = []
    class Process:
        pid = 90001
        def __init__(self, cmd, **kwargs): launched.append((cmd, kwargs))
        def poll(self): return None
    monkeypatch.setattr(native, 'validate', lambda *a: {'ok': True})
    monkeypatch.setattr(native, '_preflight_resources', lambda *a: None)
    monkeypatch.setattr(native.subprocess, 'Popen', Process)
    result = bridge.record_start({'profile_id': pid, 'mode': 'live', 'confirm_live_execute': True,
                                  'dataset_repo_id': 'lab/native', 'fps': 30})
    assert result['ok'] and result['status'] == 'RUNNING'
    assert result['dataset_repo_id'] == 'lab/native'
    assert launched[0][0][3] == 'record'
    assert launched[0][1]['start_new_session'] is True
    assert 'PYTHONPATH' not in launched[0][1]['env']
    assert result['session_id'] in bridge._native_input_fds
    os.close(bridge._native_input_fds.pop(result['session_id']))
    bridge._close_log_handle(result['session_id'])


def test_mismatched_explicit_profile_cannot_stop_native_session(bridge):
    from types import SimpleNamespace
    bridge._sessions['n'] = {'session_id': 'n', 'native_rebot': True, 'profile_id': 'rebot_b601_rs', 'workflow': 'teleoperate', 'status': 'RUNNING'}
    bridge._processes['n'] = SimpleNamespace(pid=90001, poll=lambda: None,
        send_signal=lambda _: pytest.fail('Mismatched profile must not stop this session'))
    result = bridge.teleoperate_stop({'profile_id': 'robotis_omx_ai', 'session_id': 'n'})
    assert not result['ok']


def test_public_native_session_never_runs_omx_postprocessing(bridge, monkeypatch):
    monkeypatch.setattr(bridge, '_refresh_in_process_isaac_mirror_progress', lambda *a: pytest.fail('OMX postprocessor invoked'))
    session = {'session_id': 'n', 'native_rebot': True, 'profile_id': 'rebot_b601_rs', 'workflow': 'record', 'status': 'RUNNING'}
    assert bridge._public_session(session)['native_rebot'] is True
