"""Native LeRobot CLI boundary: scoped keyboard input and startup cleanup.

No action processing or motor settings are changed. Native factories and loops
are reused; the outer finally also covers connect(), before upstream's finally.
"""
import importlib
import signal
import sys


def cleanup(devices):
    errors = []
    seen = set()
    def release(device):
        if id(device) in seen:
            return
        seen.add(id(device))
        try:
            if hasattr(device, 'left_arm') and hasattr(device, 'right_arm'):
                release(device.left_arm)
                release(device.right_arm)
            elif device.is_connected:
                device.disconnect()
            # A failed Quest Robot.connect can leave the paired leader ref alive.
            session = getattr(device, 'session', None)
            if session is not None and getattr(session, 'refs', 0):
                session.stop_video()
                session.detach(force=True)
            bus = getattr(device, 'bus', None)
            if device.is_connected or (bus is not None and getattr(bus, 'is_connected', True)):
                errors.append(f'{type(device).__name__}: cleanup incomplete')
        except Exception as exc:
            errors.append(f'{type(device).__name__}: {exc}')
    for device in reversed(devices):
        release(device)
    if errors:
        raise RuntimeError('; '.join(errors))


def run(module):
    devices = []
    originals = {}
    for name in ('make_robot_from_config', 'make_teleoperator_from_config'):
        original = getattr(module, name)
        originals[name] = original
        def tracked(config, factory=original):
            device = factory(config)
            devices.append(device)
            return device
        setattr(module, name, tracked)
    try:
        module.main()
    except KeyboardInterrupt:
        pass
    finally:
        previous = signal.signal(signal.SIGINT, signal.SIG_IGN)
        try:
            cleanup(devices)
            print('AX4LAB_REBOT_CLEANUP_OK', flush=True)
        finally:
            signal.signal(signal.SIGINT, previous)
            for name, original in originals.items():
                setattr(module, name, original)


def main():
    workflow = sys.argv[1]
    if workflow not in ('teleoperate', 'record'):
        raise ValueError('Unsupported native workflow')
    if workflow == 'record':
        from lerobot.utils import keyboard_input
        keyboard_input.pynput_can_capture = lambda: False
    module = importlib.import_module(f'lerobot.scripts.lerobot_{workflow}')
    sys.argv = [f'lerobot-{workflow}', *sys.argv[2:]]
    run(module)


if __name__ == '__main__':
    main()
