from __future__ import annotations

from pathlib import Path

from devclaw.adapters.verification import VerificationAdapter
from devclaw.core.models import AcceptanceContract, ProjectBrief, VerificationReport


class QAAgent:
    name = "QA Agent"

    def __init__(self, adapter: VerificationAdapter):
        self.adapter = adapter

    def run(
        self,
        brief: ProjectBrief,
        contract: AcceptanceContract,
        workspace: Path,
    ) -> VerificationReport:
        return self.adapter.verify(brief, contract, workspace)
