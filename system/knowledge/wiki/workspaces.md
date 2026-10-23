---
{"topic_id":"workspaces","owner":"documentation","source_refs":["system/runtime/runtime_ide.md","system/device_bridges/README.md","system/knowledge/wiki_memory.md","system/agents/orchestrator_agent.md"],"source_revision":{"system/runtime/runtime_ide.md":"3cb6a2c2f0e1c047d09d23ecac5fb32850aec6871b90f05c4799bfbb3d540880","system/device_bridges/README.md":"be250afdc9729e2012c59961c30dd4a7521a0e15383201662fc1e69e21ad72f3","system/knowledge/wiki_memory.md":"d0175eafee9ed4635f30ead2b838cc5f877db3faff6e9484bb7fcf8a364b6210","system/agents/orchestrator_agent.md":"2888451d18c8742c9f88f9f976f2fc3439507d1527cc73519fe74804b92c7964"},"verified_at":"2026-09-29T00:00:00+09:00","applicability":"Public AX4LAB reference: workspaces","status":"reviewed"}
---

# Workspaces — Where to Inspect the System

AX4LAB separates model/run control, experiment monitoring, configuration and device diagnostics. Opening a screen or selecting an item does not itself approve or execute an experiment.

| Screen | Primary purpose |
|---|---|
| Main GUI | Model/run controls and workspace entry points |
| Live GUI | Research conversation, Setup, agent Reports and evidence |
| Runtime IDE | Graph/module structure, connections, validation and versions |
| Device Workspace | Bridge connections, settings, state and manual diagnostics |
| Knowledge Workspace | Wiki, Memory, Source Library, Delivery and Ontology |

## Reading Live GUI

First check the run and selected agent. Report presents owner progress/results, Artifacts exposes related files, and Timeline shows event order. Conversation text and device telemetry are not themselves agent-completion decisions.

Experimental Setup shows conditions and setting state. Message expansion and Chat pin affect presentation, not the backend contract.

## Runtime IDE

Package configuration, graph attachment, module application and execution are different states. Structural edits pass existing validation, save and activation boundaries. Deleting a node does not automatically create an alternative path.

Read LLM, LLM call and CODE relationships using the [control-level guide](control-levels.md).

## Device workspaces

Inspect printer providers, robot environments, camera observations and test-machine task connections in their owning bridge workspace. Manual controls may have real physical effects. Work performed outside the automatic experiment is not automatic handoff-success evidence.

[Runtime IDE reference](../../runtime/runtime_ide.md), [bridge index](../../device_bridges/README.md), [artifact explorer](artifacts.md).
