---
{"topic_id":"recovery","owner":"documentation","source_refs":["system/agents/equipment_agent.md","system/agents/vision_agent.md","system/agents/analysis_agent.md","system/device_bridges/plc_safety_bridge.md"],"source_revision":{"system/agents/equipment_agent.md":"2ca8e0c1ac8a767530dd1bdc96ec6b9790d41751ea75d70f3a03995eda159e00","system/agents/vision_agent.md":"9d3623a8d9c7b2f394557ddfcdf14ce6c4f321a77192e81bfb157467c2adcbab","system/agents/analysis_agent.md":"5337a2e66829045faaec2161705a3c0904f69f6cdbcc1a21ecdcbe3f42b877de","system/device_bridges/plc_safety_bridge.md":"ea74d0d8d765ee1f68ad3bf37f759eed30ad03c1d7a18789a1835cc2aa54e60a"},"verified_at":"2026-09-29T00:00:00+09:00","applicability":"Public AX4LAB reference: recovery","status":"reviewed"}
---

# Recovery — Resume and Archived Evidence

Recovery establishes what actually completed and what may continue without replay. It does not simply relabel failure as success. Device stop state and data postprocessing are separate decisions.

| State | Review path |
|---|---|
| Paused | Resume under existing conditions |
| Test completed; terminal review failed | Revalidate run, specimen, CSV hash and completed tasks |
| Requested archived-image review | Non-actuating review of the historical scene |
| Partial execution or unknown effects | Hold; do not repeat automatically |

Original compression CSV, completed Skills/replays and image timestamps/hashes are evidence. Preserve them; do not overwrite old decisions or give historical images a current timestamp.

## Historical images

Explicit archived review assesses the scene at capture time. It is not current physical clearance. A scoped path may retain the safety hold while continuing saved-data Analysis, Knowledge, BO and limited next Design. This is separate from resuming physical experiments.

Stopping at the next Design is a one-off recovery scope, not a permanent experiment rule or fabrication permission.

## Server and code application

Checkpoint restoration and limited hot reload do not actuate equipment. Hot reload validates supported modules at an inactive boundary; it cannot replace active/paused work or arbitrary modules. A controlled server update may still be required.

Recovery does not automatically clear PLC latches, operator stops or owner approvals. Past success cannot authorize new actuation when current effects are unknown.

[Equipment recovery contract](../../agents/equipment_agent.md), [Vision historical review](../../agents/vision_agent.md), [PLC safety boundary](../../device_bridges/plc_safety_bridge.md).
