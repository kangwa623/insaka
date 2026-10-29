"""The Insaka agent: prepares each case with tools, stops where people decide.

    python -m insaka.agent MWILA-001
"""

import json
from pathlib import Path

from ..parsing import parse_statement
from .loop import run_agent
from .tools import AgentCase, NoChat, csv_sources, pdf_sources

__all__ = ["AgentCase", "NoChat", "build_case", "run_agent", "run_case"]


UPLOADS_DIR = Path("data/uploads")


def build_case(client_id: str, data_dir: str | Path = "data/synthetic", absa_months: int | None = None,
               uploads_dir: str | Path = UPLOADS_DIR, **settings) -> AgentCase:
    """A case for one client: statements the customer or RM uploaded come first, then the
    statement PDFs when present, else the CSVs."""
    data_dir = Path(data_dir)
    clients = {c["client_id"]: c for c in json.loads((data_dir / "clients.json").read_text("utf-8"))}
    client = clients[client_id]
    pdfs = [data_dir / "statements" / f"{client_id}_{ch}.pdf" for ch in client["channels"]]
    if absa_months is None and all(p.exists() for p in pdfs):
        sources = pdf_sources(client, data_dir / "statements")
    else:
        truth = json.loads((data_dir / "ground_truth.json").read_text("utf-8"))[client_id]
        sources = csv_sources(data_dir, client, truth, absa_months)
    for ch in client["channels"]:
        uploaded = Path(uploads_dir) / f"{client_id}_{ch}.pdf"
        if uploaded.exists():
            sources[ch] = lambda p=uploaded, c=ch: parse_statement(p, f"{client_id}-{c.upper()}")
    return AgentCase(client=client, sources=sources, **settings)


def run_case(client_id: str, mode: str = "llm", data_dir: str | Path = "data/synthetic",
             cases_dir: str | Path = "data/cases", agent_dir: str | Path = "data/agent",
             chat=None, label: str = "", absa_months: int | None = None,
             uploads_dir: str | Path = UPLOADS_DIR, assigned_rm: str | None = None, **settings):
    """Run the agent on one client and open the case file for people to act on."""
    from ..case import DEFAULT_RM, open_case

    settings.setdefault("memo_out", cases_dir)
    case = build_case(client_id, data_dir, absa_months, uploads_dir, **settings)
    run = run_agent(case, chat=chat, mode=mode, cache_dir=agent_dir, label=label)
    return run, case, open_case(run, case, Path(cases_dir), assigned_rm or DEFAULT_RM)
