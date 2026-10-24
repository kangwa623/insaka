"""Synthetic borrower profiles: who they are, what they applied for, and the hidden
parameters that drive their transactions."""

import numpy as np

from .archetypes import ARCHETYPES, MWILA_ARCHETYPE, Archetype
from .findings import choose_findings

FEMALE_NAMES = ("Chileshe", "Mutale", "Bupe", "Chanda", "Mwape", "Thandiwe", "Lweendo",
                "Namukolo", "Mapalo", "Taonga", "Chipo", "Nkandu", "Mwaka", "Ruth", "Grace",
                "Esther", "Memory", "Precious", "Agness", "Mutinta", "Tiza", "Natasha",
                "Musonda", "Chisomo", "Towela", "Inonge", "Beatrice", "Loveness")
MALE_NAMES = ("Mulenga", "Chola", "Mwansa", "Lubinda", "Joseph", "Emmanuel", "Patrick",
              "Chisanga", "Kondwani", "Mumba", "Kabwe", "Bwalya", "Moses", "Brian", "Kelvin",
              "Elijah", "Mwila", "Sipho", "Mubanga", "Hamweemba", "Jacob", "Lazarus",
              "Davies", "Chimuka", "Nchimunya", "Mapopa", "Felix", "Gift")
SURNAMES = ("Banda", "Phiri", "Mwale", "Tembo", "Zulu", "Lungu", "Mulenga", "Mwansa",
            "Chanda", "Musonda", "Bwalya", "Sakala", "Daka", "Ngoma", "Kunda", "Mumba",
            "Chilufya", "Kapembwa", "Sichone", "Hamoonga", "Muleya", "Mweemba", "Siame",
            "Nyirenda", "Mbewe", "Kalaba", "Mutale", "Simbeye", "Lubinda", "Mwiinga")

PROVINCES = {
    "Lusaka": ("Lusaka", "Chongwe", "Kafue"),
    "Copperbelt": ("Ndola", "Kitwe", "Chingola", "Mufulira"),
    "Central": ("Kabwe", "Mkushi", "Serenje"),
    "Eastern": ("Chipata", "Petauke", "Katete", "Lundazi"),
    "Southern": ("Choma", "Livingstone", "Monze", "Mazabuka"),
    "Northern": ("Kasama", "Mbala", "Mporokoso"),
    "Muchinga": ("Chinsali", "Mpika", "Nakonde"),
    "Luapula": ("Mansa", "Samfya", "Kawambwa"),
    "North-Western": ("Solwezi", "Kasempa", "Mwinilunga"),
    "Western": ("Mongu", "Senanga", "Kaoma"),
}

MTN_PREFIXES = ("096", "076")
AIRTEL_PREFIXES = ("097", "077")


def mask_phone(rng: np.random.Generator, prefixes=MTN_PREFIXES + AIRTEL_PREFIXES) -> str:
    return f"{rng.choice(prefixes)}****{rng.integers(100, 1000)}"


def mask_account(rng: np.random.Generator) -> str:
    return f"****{rng.integers(1000, 10000)}"


def instalment(amount: float, tenor_months: int, annual_rate: float = 0.28) -> float:
    """Monthly repayment on a flat-rate loan, which is how most SME loans are quoted."""
    return amount * (1 + annual_rate * tenor_months / 12) / tenor_months


def _round_to(value: float, step: int) -> int:
    return int(max(step, round(value / step) * step))


def make_profile(index: int, rng: np.random.Generator) -> dict:
    archetype: Archetype = ARCHETYPES[rng.integers(len(ARCHETYPES))]
    gender = "F" if rng.random() < 0.5 else "M"
    first = rng.choice(FEMALE_NAMES if gender == "F" else MALE_NAMES)
    surname = rng.choice(SURNAMES)
    province = list(PROVINCES)[rng.integers(len(PROVINCES))]
    town = rng.choice(PROVINCES[province])

    low, high = archetype.income_range
    base_income = float(np.exp(rng.uniform(np.log(low), np.log(high))))
    n_months = int(rng.integers(6, 13))
    tenor = int(rng.choice([6, 12, 12, 18, 24]))
    requested = _round_to(np.clip(base_income * rng.uniform(1.0, 6.0), 10_000, 1_000_000), 500)

    channels = {"absa": mask_account(rng)}
    if rng.random() < 0.75:
        channels["mtn"] = mask_phone(rng, MTN_PREFIXES)
    if rng.random() < 0.40 or len(channels) == 1 and rng.random() < 0.6:
        channels["airtel"] = mask_phone(rng, AIRTEL_PREFIXES)

    findings = choose_findings(rng, archetype, n_months)
    bureau = rng.choice(["no_hit", "clean", "adverse"], p=[0.55, 0.35, 0.10])

    profile = {
        "client_id": f"ZM-{index:04d}",
        "owner_name": f"{first} {surname}",
        "gender": gender,
        "age": int(rng.integers(22, 61)),
        "province": province,
        "town": str(town),
        "business_name": f"{surname} {rng.choice(archetype.name_suffixes)}",
        "business_type": archetype.label,
        "archetype": archetype.key,
        "sector": archetype.sector,
        "years_trading": int(rng.integers(1, 16)),
        "months_of_history": n_months,
        "channels": channels,
        "application": {
            "requested_amount": requested,
            "tenor_months": tenor,
            "purpose": "Working capital" if archetype.sector == "sme" else "Seasonal inputs and stock",
            "pacra_registered": bool(rng.random() < 0.85),
            "tpin_registered": bool(rng.random() < 0.70),
            "bureau_status": str(bureau),
            # Owners tend to overstate turnover on forms.
            "declared_monthly_turnover": _round_to(base_income * rng.uniform(0.8, 1.6), 100),
        },
    }
    hidden = _hidden_params(rng, archetype, base_income, findings, bureau)
    return {"profile": profile, "hidden": hidden, "archetype": archetype}


def _hidden_params(rng, archetype: Archetype, base_income: float, findings: list, bureau) -> dict:
    heavy_overdraft = "heavy_overdraft" in findings
    return {
        "base_income": base_income,
        "season": archetype.season,
        "volatility": 0.75 if "irregular_inflows" in findings else float(rng.uniform(0.08, 0.28)),
        "cogs_ratio": float(rng.uniform(*archetype.cogs_ratio)),
        "momo_share": float(rng.uniform(*archetype.momo_share)),
        "findings": findings,
        "overdraft_limit": _round_to(base_income * 0.9, 500) if heavy_overdraft else 0,
        "rent": _round_to(base_income * rng.uniform(0.04, 0.10), 50) if rng.random() < 0.6 else 0,
        "children_in_school": int(rng.choice([0, 1, 2, 3], p=[0.3, 0.3, 0.25, 0.15])),
        "staff": int(min(6, base_income // 15_000)) if base_income > 15_000 else 0,
        "existing_loan_instalment": (_round_to(base_income * rng.uniform(0.05, 0.15), 50)
                                     if bureau != "no_hit" and rng.random() < 0.6 else 0),
        "n_customers": int(np.clip(base_income / archetype.ticket / 3, 15, 80)),
        "draw_rate": float(rng.uniform(0.45, 0.75)),
    }


def mwila_profile() -> dict:
    """The demo borrower. Fixed values so the story is the same on every run."""
    rng = np.random.default_rng(20261026)
    archetype = MWILA_ARCHETYPE
    profile = {
        "client_id": "MWILA-001",
        "owner_name": "Mwila Tembo",
        "gender": "F",
        "age": 38,
        "province": "Eastern",
        "town": "Chipata",
        "business_name": "Tembo Maize & Inputs",
        "business_type": archetype.label,
        "archetype": archetype.key,
        "sector": archetype.sector,
        "years_trading": 7,
        "months_of_history": 12,
        "channels": {"absa": "****4821", "mtn": "096****318"},
        "application": {
            "requested_amount": 25_000,
            "tenor_months": 12,
            "purpose": "Seed and fertiliser stock ahead of the planting season",
            "pacra_registered": True,
            "tpin_registered": True,
            "bureau_status": "no_hit",
            "declared_monthly_turnover": 20_000,
        },
    }
    hidden = {
        "base_income": 18_000.0,
        "season": archetype.season,
        "volatility": 0.10,
        "cogs_ratio": 0.58,
        "momo_share": 0.55,
        "findings": ["seasonal_income"],
        "overdraft_limit": 0,
        "rent": 800,
        "children_in_school": 2,
        "staff": 1,
        "existing_loan_instalment": 0,
        "n_customers": 35,
        "draw_rate": 0.45,
    }
    return {"profile": profile, "hidden": hidden, "archetype": archetype, "rng": rng}
