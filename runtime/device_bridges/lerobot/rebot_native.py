"""Native Rebot adapter behind the existing LeRobot GUI endpoints.

No OMX processors, device factories, or physical-runtime lifecycle calls here.
Only the installed LeRobot CLI owns the robot and its cleanup.
"""
from __future__ import annotations

import copy
import json
import os
import pty
from pathlib import Path
import signal
import subprocess
import threading
from datetime import datetime, timezone

TYPES = {
    'rebot_b601_rs': ('bi_rebot_b601_follower', 'bi_rebot_102_leader'),
    'rebot_b601_rs_quest': ('rebot_vr', 'quest3'),
}
LOCK = threading.RLock()


def selected(bridge, payload):
    payload = payload or {}
    session = bridge._sessions.get(str(payload.get('session_id') or ''), {})
    return profile_id(bridge, payload) in TYPES or session.get('profile_id') in TYPES


def profile_id(bridge, payload):
    session = bridge._sessions.get(str(payload.get('session_id') or ''), {})
    return str(payload.get('profile_id') or session.get('profile_id') or bridge._selected_profile_id)


def environment():
    env = {k: v for k, v in os.environ.items() if not k.startswith(('ATR_', 'AX4LAB_'))}
    for key in ('PYTHONPATH', 'PYTHONHOME'):
        env.pop(key, None)
    env.update(PYTHONUNBUFFERED='1', OPENBLAS_NUM_THREADS='1', OMP_NUM_THREADS='1',
               MKL_NUM_THREADS='1', NUMEXPR_NUM_THREADS='1')
    return env


def load_settings(bridge, profile_id):
    return copy.deepcopy(bridge._load_device_memory().get('profiles', {}).get(profile_id, {}).get('native_settings', {}))


def save_settings(bridge, profile_id, value):
    if profile_id not in TYPES:
        raise ValueError('Not a Rebot native profile')
    if not isinstance(value, dict) or set(value) != {'python', 'config'}:
        raise ValueError('Settings require python and config')
    python = Path(str(value['python'])).expanduser()
    if not python.is_absolute() or not python.is_file() or not os.access(python, os.X_OK):
        raise ValueError('Select an absolute, executable Python path from the Rebot environment')
    cfg = value['config']
    if not isinstance(cfg, dict) or set(cfg) - {'robot', 'teleop', 'fps', 'display_data'}:
        raise ValueError('Native config accepts robot, teleop, fps and display_data')
    for role, expected in zip(('robot', 'teleop'), TYPES[profile_id]):
        if not isinstance(cfg.get(role), dict) or cfg[role].get('type') != expected:
            raise ValueError(f'{role}.type must be {expected}')
    if profile_id == 'rebot_b601_rs':
        for side in ('left_arm_config', 'right_arm_config'):
            arm = cfg['robot'].get(side, {})
            if not isinstance(arm, dict) or arm.get('motor_family') != 'rs' or arm.get('can_adapter') != 'socketcan' or not arm.get('port'):
                raise ValueError(f'robot.{side} requires RS / SocketCAN / port')
            leader = cfg['teleop'].get(side)
            if not isinstance(leader, dict) or not leader.get('port'):
                raise ValueError(f'teleop.{side}.port is required')
        if cfg['robot']['left_arm_config']['port'] == cfg['robot']['right_arm_config']['port']:
            raise ValueError('Left and right CAN interfaces must differ')
    if isinstance(cfg.get('fps', 30), bool) or not 1 <= float(cfg.get('fps', 30)) <= 100:
        raise ValueError('Control FPS must be between 1 and 100')
    with LOCK:
        memory = bridge._load_device_memory()
        memory.setdefault('profiles', {}).setdefault(profile_id, {})['native_settings'] = copy.deepcopy(value)
        bridge._save_device_memory(memory)
    return load_settings(bridge, profile_id)


def _arguments(value, prefix=''):
    args = []
    for key, item in value.items():
        name = f'{prefix}.{key}' if prefix else key
        if isinstance(item, dict) and key in ('robot', 'teleop', 'dataset', 'left_arm_config', 'right_arm_config'):
            args.extend(_arguments(item, name))
        else:
            encoded = item if isinstance(item, str) else json.dumps(item, separators=(',', ':'))
            args.append(f'--{name}={encoded}')
    return args


def command(bridge, profile_id, workflow, payload):
    if workflow not in ('teleoperate', 'record'):
        raise ValueError('Rebot native adapter supports teleoperate and record; policy/replay is not connected')
    value = load_settings(bridge, profile_id)
    if not value:
        raise ValueError('Save the Rebot Python path and native configuration first')
    cfg = copy.deepcopy(value['config'])
    fps = payload.get('fps') if payload.get('fps') is not None else cfg.get('fps', 30)
    if isinstance(fps, bool) or not isinstance(fps, (int, float)) or not 1 <= fps <= 100 or int(fps) != fps:
        raise ValueError('Control FPS must be an integer between 1 and 100')
    cfg.pop('fps', None)
    cfg['display_data'] = bool(payload.get('display_data', cfg.get('display_data', False)))
    if workflow == 'teleoperate':
        cfg['fps'] = fps
        if payload.get('teleop_time_s') is not None:
            cfg['teleop_time_s'] = payload['teleop_time_s']
    else:
        from mcp_tools.lerobot_schemas import LeRobotSessionRequest
        request = LeRobotSessionRequest.model_validate(payload)
        request = request.model_copy(update={'dataset_repo_id': request.dataset_repo_id or 'local/rebot'})
        cfg['dataset'] = {
            'repo_id': request.dataset_repo_id,
            'root': bridge._dataset_path_for(request),
            'single_task': request.task_instruction or 'Rebot demonstration',
            'fps': fps, 'episode_time_s': request.episode_s, 'reset_time_s': request.reset_s,
            'num_episodes': request.num_episodes, 'push_to_hub': request.push_to_hub,
        }
        cfg['resume'] = request.resume
        cfg['play_sounds'] = False
    entry = [str(Path(__file__).resolve().parents[2] / 'scripts/rebot_native_runner.py'), workflow]
    return [value['python'], '-u', *entry, *_arguments(cfg)]


def validate(bridge, profile_id, workflow='teleoperate', payload=None):
    """Parse with the actual installed LeRobot version; never construct a robot."""
    cmd = command(bridge, profile_id, workflow, payload or {})
    probe = Path(__file__).resolve().parents[2] / 'scripts/rebot_config_probe.py'
    result = subprocess.run([cmd[0], str(probe), workflow], input=json.dumps(cmd[4:]),
                            capture_output=True, text=True, env=environment(), timeout=60)
    if result.returncode:
        raise ValueError((result.stderr or result.stdout)[-4000:].strip())
    return {'ok': True, 'profile_id': profile_id, 'workflow': workflow,
            'command_preview': cmd, 'validation': 'native_config_parsed', 'actuation_performed': False}


def _session(bridge, workflow, payload):
    pid = profile_id(bridge, payload)
    sid = str(payload.get('session_id') or '')
    candidates = [s for s in bridge._sessions.values() if s.get('profile_id') == pid and s.get('workflow') == workflow]
    if sid:
        return next((s for s in candidates if s['session_id'] == sid), None)
    return candidates[-1] if candidates else None


def response(bridge, session, **extra):
    proc = bridge._processes.get(session['session_id'])
    if proc is not None:
        code = proc.poll()
        session['returncode'] = code
        if code is not None:
            clean = 'AX4LAB_REBOT_CLEANUP_OK' in bridge._tail_file(session.get('log_path', ''))
            session['status'] = ('STOPPED' if session.get('stop_requested') else 'COMPLETED') if code in (0, 130) and clean else 'FAILED'
            session['cleanup_verified'] = clean
            bridge._close_log_handle(session['session_id'])
            fd = bridge._native_input_fds.pop(session['session_id'], None)
            if fd is not None:
                os.close(fd)
    tail = bridge._tail_file(session.get('log_path', ''))
    return {**session, 'ok': session['status'] != 'FAILED', 'log_tail': tail,
            'runtime_phase': session['status'], 'runtime_message': 'Native LeRobot session',
            'events': session.get('step_trace', []), **extra}


def status(bridge, workflow, payload):
    session = _session(bridge, workflow, payload)
    if session is None:
        return {'ok': not bool(payload.get('session_id')), 'status': 'IDLE',
                'profile_id': payload.get('profile_id') or bridge._selected_profile_id,
                'session_id': '', 'workflow': workflow, 'message': 'No matching native session'}
    return response(bridge, session)


def _preflight_resources(bridge, profile_id):
    cfg = load_settings(bridge, profile_id)['config']
    # No CAN writes or device opens: the native driver performs real connection checks.
    if profile_id == 'rebot_b601_rs':
        for side in ('left_arm_config', 'right_arm_config'):
            port = str(cfg['robot'][side]['port'])
            if '/' in port or not Path('/sys/class/net', port).exists():
                raise ValueError(f'CAN interface is missing: {port}')
            port = str(cfg['teleop'][side]['port'])
            if not Path(port).exists():
                raise ValueError(f'Leader port is missing: {port}')
    # Avoid starting a second owner beside an externally launched physical session.
    owned = {p.pid for p in bridge._processes.values() if p.poll() is None}
    for proc in Path('/proc').iterdir():
        if not proc.name.isdecimal() or int(proc.name) in owned:
            continue
        try:
            parts = proc.joinpath('cmdline').read_bytes().split(b'\0')
        except OSError:
            continue
        if is_external_owner(parts):
            raise ValueError('An external native LeRobot session is active; stop it before starting another')


def is_external_owner(parts):
    if any(p.endswith(b'hardware_sink.py') for p in parts) and b'--drive' in parts:
        return True
    return any(p in (b'lerobot.scripts.lerobot_teleoperate', b'lerobot.scripts.lerobot_record')
               or p.rsplit(b'/', 1)[-1] in (b'lerobot-teleoperate', b'lerobot-record', b'rebot_native_runner.py') for p in parts)


def start(bridge, workflow, payload):
    from mcp_tools.lerobot_schemas import LeRobotSessionRequest
    request = LeRobotSessionRequest.model_validate(payload)
    pid = request.profile_id or bridge._selected_profile_id
    mode = request.runtime_mode or request.mode
    with LOCK:
        try:
            cmd = command(bridge, pid, workflow, payload)
            if mode != 'live':
                return {'ok': True, 'mode': mode, 'profile_id': pid, 'status': 'PREVIEW',
                        'workflow': workflow, 'command_preview': cmd, 'actuation_performed': False}
            if not request.confirm_live_execute:
                raise ValueError('Confirm live execution before starting a Rebot session')
            profile = bridge._profile(pid)
            gates = profile.safety_limits if profile is not None else {}
            allow = 'allow_recording' if workflow == 'record' else 'allow_teleoperation'
            if not gates.get('live_enabled') or not gates.get(allow):
                raise ValueError('This profile does not allow live execution for this workflow')
            for item in bridge._sessions.values():
                proc = bridge._processes.get(item.get('session_id'))
                if proc is not None and proc.poll() is None and item.get('workflow') in ('teleoperate', 'record', 'rollout', 'replay'):
                    raise ValueError('Another managed robot session is active')
            validate(bridge, pid, workflow, payload)
            _preflight_resources(bridge, pid)
            sid = bridge._new_session_id(workflow)
            bridge.config.session_log_root.mkdir(parents=True, exist_ok=True)
            log_path = bridge.config.session_log_root / f'{sid}.log'
            handle = log_path.open('w', encoding='utf-8')
            master, slave = pty.openpty() if workflow == 'record' else (None, None)
            try:
                process = subprocess.Popen(cmd, cwd=str(bridge._runtime_root), env=environment(),
                                           stdin=slave if slave is not None else subprocess.DEVNULL,
                                           stdout=handle, stderr=subprocess.STDOUT, start_new_session=True)
            except BaseException:
                handle.close()
                if master is not None:
                    os.close(master)
                raise
            finally:
                if slave is not None:
                    os.close(slave)
            if master is not None:
                bridge._native_input_fds[sid] = master
            bridge._processes[sid] = process
            bridge._log_handles[sid] = handle
            session = {'session_id': sid, 'profile_id': pid, 'workflow': workflow, 'mode': 'live',
                       'status': 'RUNNING', 'pid': process.pid, 'returncode': None, 'native_rebot': True,
                       'created_at': datetime.now(timezone.utc).isoformat(), 'log_path': str(log_path),
                       'command_preview': cmd, 'step_trace': [{'step': 'PROCESS_STARTED', 'status': 'active',
                                                             'detail': 'Native CLI started; inspect log for device readiness'}]}
            if workflow == 'record':
                request = request.model_copy(update={'dataset_repo_id': request.dataset_repo_id or 'local/rebot'})
                session.update(dataset_repo_id=request.dataset_repo_id,
                               dataset_path=bridge._dataset_path_for(request),
                               num_episodes=request.num_episodes, episode_s=request.episode_s,
                               reset_s=request.reset_s, fps=payload.get('fps') or load_settings(bridge, pid)['config'].get('fps', 30))
            bridge._sessions[sid] = session
            return response(bridge, session)
        except (ValueError, OSError, subprocess.SubprocessError) as exc:
            return {'ok': False, 'status': 'FAILED', 'profile_id': pid, 'workflow': workflow,
                    'failure_code': 'REBOT_NATIVE_START_FAILED', 'message': str(exc)}


def stop(bridge, workflow, payload):
    with LOCK:
        session = _session(bridge, workflow, payload)
        if session is None:
            return {'ok': not bool(payload.get('session_id')), 'status': 'IDLE', 'message': 'No matching native session'}
        process = bridge._processes.get(session['session_id'])
        if process is not None and process.poll() is None and not session.get('stop_requested'):
            # SIGINT to the CLI only: let its finally/disconnect close the CAN owner.
            # Do not kill its cleanup subprocesses or any other robot session.
            try:
                process.send_signal(signal.SIGINT)
            except ProcessLookupError:
                return response(bridge, session)
            session['stop_requested'] = True
            session['status'] = 'STOPPING'
        return response(bridge, session)


def control(bridge, payload):
    action = payload.get('action')
    if action == 'stop':
        return stop(bridge, 'record', payload)
    session = _session(bridge, 'record', payload)
    if not session or not bridge._processes.get(session['session_id']) or bridge._processes[session['session_id']].poll() is not None:
        return {'ok': False, 'message': 'No active native recording session'}
    if action in ('next', 'retry') and bridge._record_log_phase(session) == 'saving':
        return {'ok': False, 'message': 'Wait until the current episode finishes saving'}
    keys = {'next': b'\x1b[C', 'retry': b'\x1b[D', 'finish': b'\x1b'}
    fd = bridge._native_input_fds.get(session['session_id'])
    if action not in keys or fd is None:
        return {'ok': False, 'message': 'Native recording terminal is unavailable'}
    if not session.get('native_controls_ready'):
        session['native_controls_ready'] = 'Using terminal keyboard input' in bridge._tail_file(session.get('log_path', ''), max_chars=100000)
    if not session.get('native_controls_ready'):
        return {'ok': False, 'message': 'Recording controls are not ready; wait for the native keyboard listener'}
    try:
        os.write(fd, keys[action])
    except OSError as exc:
        return {'ok': False, 'message': f'Native recording terminal is unavailable: {exc}'}
    return response(bridge, session, control={'status': 'submitted', 'action': action},
                    message='Control submitted to this recording session; check the episode log for completion')


def protected_pids(bridge):
    roots = [process.pid for sid, process in bridge._processes.items()
             if bridge._sessions.get(sid, {}).get('native_rebot') and process.poll() is None]
    return set(bridge._expand_descendant_pids(roots))


def shutdown(bridge):
    results = [stop(bridge, session['workflow'], {'session_id': sid})
               for sid, session in list(bridge._sessions.items()) if session.get('native_rebot')]
    return results
