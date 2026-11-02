"""Declarative discovery entry, with no serial dependency or side effects."""
import json
from device_bridges.module_contract import BridgeModule

MODULE = BridgeModule('serial_communication','1.0.0',json.dumps({
    'name':'Serial Communication',
    'workspace':'/serial',
    'api_prefix':'/api/serial',
    'device_catalog':'device_bridges/serial_communication/modules',
    'manual_connection_only':True,
}))
