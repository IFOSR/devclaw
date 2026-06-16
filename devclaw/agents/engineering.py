from __future__ import annotations

from pathlib import Path

from devclaw.adapters.execution import ExecutionAdapter
from devclaw.core.models import AcceptanceContract, AgentOutput, ProjectBrief


class EngineerAgent:
    name = "Engineer Agent"

    def __init__(self, adapter: ExecutionAdapter):
        self.adapter = adapter

    def run(
        self,
        brief: ProjectBrief,
        contract: AcceptanceContract,
        workspace: Path,
    ) -> AgentOutput:
        return self.adapter.execute(brief, contract, workspace)
