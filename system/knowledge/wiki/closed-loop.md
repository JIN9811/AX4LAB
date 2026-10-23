---
{"topic_id":"closed-loop","owner":"documentation","source_refs":["system/agents/agent_api_connection_matrix.md","system/agents/equipment_agent.md","system/agents/bo_agent.md","system/agents/orchestrator_agent.md"],"source_revision":{"system/agents/agent_api_connection_matrix.md":"e4d50b413a009f3f05a23f308fc9ce36477e2d96744ba43c3b0bbeda7f575643","system/agents/equipment_agent.md":"2ca8e0c1ac8a767530dd1bdc96ec6b9790d41751ea75d70f3a03995eda159e00","system/agents/bo_agent.md":"7a84280d0d317523f6ffe442981c199ec0b1d1539465e8d79a7f405f7a9bf8b2","system/agents/orchestrator_agent.md":"2888451d18c8742c9f88f9f976f2fc3439507d1527cc73519fe74804b92c7964"},"verified_at":"2026-09-29T00:00:00+09:00","applicability":"Public AX4LAB reference: closed-loop","status":"reviewed"}
---

# Closed Loop — From Specimen to Next Design

The experiment cycle turns agreed conditions into a specimen and measurements, then feeds the results into the next design. Actual graph transitions and owner gates govern execution, not a simplified sequence diagram.

## One cycle

1. Orchestrator collects goals and conditions, defining the run contract and task scope.
2. Design preserves requested coordinates while checking candidates and manufacturing constraints.
3. Specimen Making executes fabrication and supplies evidence.
4. Vision and Manipulation perform the required observation, transfer and placement checks.
5. Lab Equipment runs the approved test Flow and exports measurements.
6. Required post-test removal involves Manipulation and a separate Vision check.
7. Analysis processes original data and validates objective metrics.
8. Knowledge curates evidence and BO computes the next coordinates.
9. The plan and existing supervisory/safety conditions lead to the next Design, completion or a hold.

## Beyond the arrows

Even an Equipment-to-Analysis summary may contain removal, home-return and visual-clearance gates. Guardian is not merely a final review step; equipment interlocks and approvals remain active at the relevant boundaries.

The first LHS request can precede measurement. This applies BO initialization policy without fabricating observations. Subsequent points follow initial-design progress or the active optimization policy.

## Completion and repetition

Each success belongs to its owner's task. Design acceptance, print completion, a valid measurement and achievement of the research goal are different states. Passing results to another cycle does not waive fixed conditions or safety checks.

[Handoff contracts](agent-contracts.md), [test modes](test-modes.md), [Equipment reference](../../agents/equipment_agent.md), [BO reference](../../agents/bo_agent.md).
