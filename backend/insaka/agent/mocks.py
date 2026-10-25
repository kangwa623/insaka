"""Mocked PACRA, ZRA and credit-bureau lookups.

No public PACRA or ZRA API is confirmed and bureau access needs a licence, so the
prototype answers from the application record plus a small fixture of planted failures
(data/mocks/registry.json). Every answer says mocked: true, and the UI shows it.
"""

import json
from pathlib import Path

REGISTRY_PATH = Path("data/mocks/registry.json")


def load_registry(path: Path = REGISTRY_PATH) -> dict:
    return json.loads(path.read_text("utf-8")) if path.exists() else {}


def pacra_lookup(client: dict, registry: dict) -> dict:
    """found / not_found (declared but missing: a red flag) / not_registered (informal)."""
    declared = client["application"]["pacra_registered"]
    if not declared:
        status = "not_registered"
    elif client["client_id"] in registry.get("pacra_not_found", []):
        status = "not_found"
    else:
        status = "found"
    return {"service": "PACRA", "mocked": True, "declared": declared, "status": status,
            "business_name": client["business_name"] if status == "found" else None,
            "company_status": "Active" if status == "found" else None}


def zra_lookup(client: dict, registry: dict) -> dict:
    """compliant / no_record (declared TPIN not found) / not_registered."""
    declared = client["application"]["tpin_registered"]
    if not declared:
        status = "not_registered"
    elif client["client_id"] in registry.get("zra_no_record", []):
        status = "no_record"
    else:
        status = "compliant"
    return {"service": "ZRA", "mocked": True, "declared": declared, "status": status}


def bureau_lookup(client: dict, registry: dict) -> dict:
    """The mandatory bureau check: clean, no_hit (thin file) or adverse."""
    return {"service": "Credit bureau", "mocked": True,
            "status": client["application"]["bureau_status"]}
