"""Validate native LeRobot CLI options without creating/connecting devices."""
import json
import sys


def main():
    from lerobot.utils.import_utils import register_third_party_plugins
    register_third_party_plugins()
    import draccus
    if sys.argv[1] == 'teleoperate':
        from lerobot.scripts.lerobot_teleoperate import TeleoperateConfig as Config
    elif sys.argv[1] == 'record':
        from lerobot.scripts.lerobot_record import RecordConfig as Config
    else:
        raise ValueError('Unsupported native workflow')
    args = json.load(sys.stdin)
    config = draccus.parse(Config, args=args)
    print(json.dumps({'ok': True, 'robot_type': config.robot.type,
                      'teleop_type': config.teleop.type, 'actuation_performed': False}))


if __name__ == '__main__':
    main()
