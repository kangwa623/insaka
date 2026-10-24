"""Per-channel ledgers: an Absa-style current account plus MTN and Airtel wallets.

Events are planned month by month, then walked in time order across all channels,
so balances, overdraft use and MoMo-to-bank transfers stay consistent with each other.
"""

import string
from datetime import datetime, timedelta

import numpy as np

from .archetypes import LANDLORDS, LENDERS, SCHOOLS
from .profiles import FEMALE_NAMES, MALE_NAMES, SURNAMES, mask_phone
from .seasons import (HARVEST_MONTHS, SCHOOL_TERM_MONTHS, SEASONAL, TAX_MONTHS,
                      days_in_month, statement_months)

# Fictional institutional buyers; one of them becomes the dominant customer.
INSTITUTIONS = ("Greenfield Millers Ltd", "Kalulu Lodge", "Mwanza Supermarket",
                "Unity Schools Kitchen", "Copper Lodge Hotel", "Lake Harvest Foods")

WALLET_NAMES = {"mtn": "MTN", "airtel": "AIRTEL"}

REF_CHARS = string.ascii_uppercase + string.digits

ABSA_RESERVE = 300.0

# Larger businesses take bigger payments rather than ever more of them.
MAX_PAYMENTS_PER_MONTH = 60


def _floor10(x: float) -> float:
    return float(np.floor(x / 10) * 10)


def _round5(x: float) -> float:
    return float(max(5, round(x / 5) * 5))


class LedgerBuilder:
    def __init__(self, entry: dict, rng: np.random.Generator):
        self.p = entry["profile"]
        self.h = entry["hidden"]
        self.a = entry["archetype"]
        self.rng = rng
        self.channels = list(self.p["channels"])
        self.wallets = [c for c in self.channels if c != "absa"]
        self.findings = self.h["findings"]
        base = self.h["base_income"]
        limit = self.h["overdraft_limit"]
        self.floor = {c: 0.0 for c in self.channels}
        # Without an overdraft, the owner's own spending leaves a reserve for bank fees,
        # so fees alone never push the account below zero.
        self.floor["absa"] = -float(limit) if limit else ABSA_RESERVE
        self.opening = {c: round(base * 0.08, 2) for c in self.wallets}
        self.opening["absa"] = round(-0.3 * limit if limit else base * 0.5, 2)
        self.events = []
        self.seq = 0
        self.monthly_takings = {}
        self._make_people()

    # ---- people the business deals with -------------------------------------------

    def _person(self, surname=None):
        rng = self.rng
        first = rng.choice(FEMALE_NAMES if rng.random() < 0.5 else MALE_NAMES)
        return {"first": str(first), "surname": str(surname or rng.choice(SURNAMES)),
                "phone": mask_phone(rng)}

    def _make_people(self):
        rng = self.rng
        owner_surname = self.p["owner_name"].split()[-1]
        self.customers = [self._person() for _ in range(self.h["n_customers"])]
        # Fairly even spread, so only the planted finding produces a dominant customer.
        self.customer_weights = rng.dirichlet(np.full(len(self.customers), 3.0))
        # Relatives usually share the owner's surname, which is a useful labelling cue.
        self.relatives = [self._person(owner_surname if rng.random() < 0.7 else None)
                          for _ in range(int(rng.integers(1, 4)))]
        self.staff = [self._person() for _ in range(self.h["staff"])]
        self.landlord = str(rng.choice(LANDLORDS))
        self.lender = str(rng.choice(LENDERS))
        self.schools = [str(s) for s in rng.choice(SCHOOLS, size=2, replace=False)]
        self.dominant = str(rng.choice(INSTITUTIONS))
        self.agents = [str(rng.integers(100000, 1000000)) for _ in range(3)]
        self.meter = f"****{rng.integers(1000, 10000)}"
        # Standing orders and loan debits always leave from the same account.
        self.rent_channel = self._pick_channel(0.7)
        self.loan_channel = self._pick_channel(0.7)

    # ---- event planning --------------------------------------------------------------

    def _ts(self, y, m, lo=1, hi=31):
        rng = self.rng
        hi = min(hi, days_in_month(y, m))
        return datetime(y, m, int(rng.integers(lo, hi + 1)), int(rng.integers(7, 20)),
                        int(rng.integers(0, 60)), int(rng.integers(0, 60)))

    def add(self, ts, channel, category, direction, desc, amount=0.0, counterparty="",
            kind="fixed", **extra):
        self.seq += 1
        self.events.append({"ts": ts, "seq": self.seq, "channel": channel, "category": category,
                            "direction": direction, "desc": desc, "amount": amount,
                            "counterparty": counterparty, "kind": kind, **extra})

    def _pick_channel(self, absa_weight=0.6):
        if not self.wallets or self.rng.random() < absa_weight:
            return "absa"
        return str(self.rng.choice(self.wallets))

    def _month_takings(self, y, m):
        h, rng = self.h, self.rng
        sigma = h["volatility"]
        noise = float(np.exp(rng.normal(-sigma ** 2 / 2, sigma)))
        takings = h["base_income"] * SEASONAL[h["season"]][m] * noise
        if "drought_shock" in self.findings and m in HARVEST_MONTHS:
            takings *= 0.35
        if (y, m) in self.dead_months:
            takings *= 0.10
        return takings

    def plan(self):
        rng, h = self.rng, self.h
        months = statement_months(self.p["months_of_history"])
        self.dead_months = set()
        if "irregular_inflows" in self.findings:
            k = int(rng.integers(1, 3))
            self.dead_months = {months[i] for i in rng.choice(len(months), size=k, replace=False)}
        for y, m in months:
            takings = self._month_takings(y, m)
            self.monthly_takings[f"{y}-{m:02d}"] = round(takings, 2)
            self._plan_income(y, m, takings)
            self._plan_costs(y, m, takings)
            self._plan_cash_management(y, m)

    def _plan_income(self, y, m, takings):
        rng, h = self.rng, self.h
        momo_total = takings * h["momo_share"] if self.wallets else 0.0
        absa_total = takings - momo_total
        cash_deposits = absa_total * 0.35
        absa_transfers = absa_total - cash_deposits
        wallet_split = {"mtn": 0.65, "airtel": 0.35} if len(self.wallets) == 2 else {
            w: 1.0 for w in self.wallets}
        momo_customer = {w: momo_total * s * 0.9 for w, s in wallet_split.items()}
        momo_agent = {w: momo_total * s * 0.1 for w, s in wallet_split.items()}

        if "dominant_customer" in self.findings:
            customer_total = absa_transfers + sum(momo_customer.values())
            dominant_amount = 0.6 * customer_total
            absa_transfers *= 0.4
            momo_customer = {w: v * 0.4 for w, v in momo_customer.items()}
            for share in rng.dirichlet(np.ones(int(rng.integers(1, 4)))):
                self.add(self._ts(y, m), "absa", "customer_payment", "credit",
                         f"EFT CR {self.dominant.upper()}", round(dominant_amount * share, 2),
                         self.dominant)

        ticket = self.a.ticket
        self._payments(y, m, "absa", absa_transfers, ticket * 3)
        for w in self.wallets:
            self._payments(y, m, w, momo_customer[w], ticket)
        for _ in range(int(rng.integers(2, 6))):
            share = cash_deposits / 4
            self.add(self._ts(y, m), "absa", "cash_deposit", "credit",
                     f"CASH DEPOSIT {self.p['town'].upper()} BRANCH",
                     _round5(share * rng.uniform(0.6, 1.4)))
        for w in self.wallets:
            if momo_agent[w] >= 50:
                desc = "Cash In via Agent" if w == "mtn" else "Cash In Agent"
                self.add(self._ts(y, m), w, "cash_deposit", "credit",
                         f"{desc} {rng.choice(self.agents)}", _round5(momo_agent[w]))

    def _payments(self, y, m, channel, total, ticket):
        rng = self.rng
        if total < 20:
            return
        n = int(np.clip(round(total / ticket), 2, MAX_PAYMENTS_PER_MONTH))
        amounts = total * rng.dirichlet(np.full(n, 2.0))
        picks = rng.choice(len(self.customers), size=n, p=self.customer_weights)
        for amount, k in zip(amounts, picks):
            c = self.customers[k]
            name = f"{c['first']} {c['surname']}".upper()
            if channel == "absa":
                desc = (f"TRF FROM {c['surname'].upper()} {c['first'][0]}" if rng.random() < 0.6
                        else f"EFT CR {name}")
            elif channel == "mtn":
                desc = f"Received from {c['phone']} {name}"
            else:
                desc = f"Money received from {c['phone']} {name}"
            self.add(self._ts(y, m), channel, "customer_payment", "credit", desc,
                     _round5(amount), name)

    def _pay(self, ts, channel, category, amount, payee, bank_desc, momo_desc=None):
        if channel == "absa":
            desc = bank_desc
        else:
            desc = momo_desc or (f"Sent to {mask_phone(self.rng)} {payee.upper()}"
                                 if channel == "mtn" else f"Money sent to {payee.upper()}")
        self.add(ts, channel, category, "debit", desc, round(amount, 2), payee)

    def _plan_costs(self, y, m, takings):
        rng, h = self.rng, self.h
        base = h["base_income"]
        overdraft = "heavy_overdraft" in self.findings

        # Suppliers: the main supplier gets paid every month.
        cogs = h["cogs_ratio"] * (0.5 * takings + 0.5 * base)
        n = int(rng.integers(2, 6))
        for i, share in enumerate(rng.dirichlet(np.full(n, 3.0))):
            supplier = self.a.suppliers[0] if i == 0 else str(rng.choice(self.a.suppliers))
            channel = "absa" if overdraft else self._pick_channel(0.65)
            ts = self._ts(y, m, 1, 6) if overdraft else self._ts(y, m)
            merchant = "Merchant Payment" if channel == "mtn" else "Pay Merchant"
            self._pay(ts, channel, "input_purchase", _round5(cogs * share), supplier,
                      f"EFT DR {supplier.upper()}", f"{merchant} {supplier}")

        if h["rent"]:
            self._pay(self._ts(y, m, 1, 5), self.rent_channel, "rent", h["rent"], self.landlord,
                      f"STANDING ORDER RENT {self.landlord.upper()}")
        for _ in range(int(rng.integers(1, 3))):
            amount = _round5(np.clip(base * rng.uniform(0.005, 0.02), 100, 2500))
            ch = self._pick_channel(0.5)
            self._pay(self._ts(y, m), ch, "utilities", amount, "ZESCO",
                      f"ZESCO PREPAID {self.meter}", f"ZESCO Token {self.meter}")
        for _ in range(int(rng.integers(2, 7))):
            amount = float(rng.choice([10, 20, 30, 50, 100, 150]))
            ch = self._pick_channel(0.15)
            label = "Data Bundle" if rng.random() < 0.4 else "Airtime Purchase"
            self._pay(self._ts(y, m), ch, "airtime_data", amount, "Airtime",
                      f"AIRTIME PURCHASE {WALLET_NAMES.get(str(rng.choice(['mtn', 'airtel'])))}",
                      label)
        for _ in range(int(rng.integers(1, 4))):
            r = self.relatives[rng.integers(len(self.relatives))]
            amount = _round5(np.clip(base * rng.uniform(0.005, 0.03), 50, 3000))
            ch = self._pick_channel(0.3)
            name = f"{r['first']} {r['surname']}"
            self._pay(self._ts(y, m), ch, "family_transfer", amount, name,
                      f"TRF TO {r['surname'].upper()} {r['first'][0]}",
                      f"Sent to {r['phone']} {name.upper()}" if ch == "mtn" else None)
        if m in SCHOOL_TERM_MONTHS:
            for child in range(h["children_in_school"]):
                school = self.schools[child % 2]
                amount = _round5(np.clip(base * rng.uniform(0.04, 0.10), 600, 9000))
                ch = self._pick_channel(0.6)
                self._pay(self._ts(y, m, 3, 20), ch, "school_fees", amount, school,
                          f"SCHOOL FEES {school.upper()}", f"Payment to {school}")
        for s in self.staff:
            amount = _round5(np.clip(base * 0.06, 1200, 3500))
            ch = self._pick_channel(0.5)
            name = f"{s['first']} {s['surname']}"
            self._pay(self._ts(y, m, 25, 28), ch, "wages", amount, name,
                      f"SALARY {name.upper()}",
                      f"Sent to {s['phone']} {name.upper()}" if ch == "mtn" else None)
        if h["existing_loan_instalment"]:
            self._pay(self._ts(y, m, 15, 20), self.loan_channel, "loan_repayment",
                      h["existing_loan_instalment"],
                      self.lender, f"LOAN REPAYMENT {self.lender.upper()}",
                      f"Loan Repayment {self.lender}")
        if self.p["application"]["tpin_registered"] and m in TAX_MONTHS:
            tpin = f"****{rng.integers(1000, 10000)}"
            self._pay(self._ts(y, m, 10, 14), "absa", "tax_payment", _round5(base * 0.04 * 3),
                      "ZRA", f"ZRA PAYMENT TPIN {tpin}")

        last = days_in_month(y, m)
        month_end = datetime(y, m, last, 23, 0, 0)
        self.add(month_end, "absa", "bank_charges", "debit", "MONTHLY SERVICE FEE", 85.0,
                 "Bank", kind="charge")
        self.add(month_end + timedelta(minutes=1), "absa", "bank_charges", "debit",
                 "SMS ALERT FEE", 10.0, "Bank", kind="charge")
        if overdraft:
            self.add(month_end + timedelta(minutes=2), "absa", "bank_charges", "debit",
                     "OVERDRAFT INTEREST", kind="od_interest", counterparty="Bank")

    def _plan_cash_management(self, y, m):
        rng, h = self.rng, self.h
        overdraft = "heavy_overdraft" in self.findings
        for w in self.wallets:
            for _ in range(int(rng.integers(1, 4))):
                ts = self._ts(y, m, 20, 28) if overdraft else self._ts(y, m, 8, 28)
                self.add(ts, w, "own_account_transfer", "debit", "", kind="sweep",
                         frac=float(rng.uniform(0.4, 0.8)))
            n_out = int(rng.integers(1, 3))
            for _ in range(n_out):
                self.add(self._ts(y, m), w, "cash_withdrawal", "debit", "", kind="draw",
                         frac=h["draw_rate"] / n_out)
        n_atm = int(rng.integers(2, 5))
        for _ in range(n_atm):
            self.add(self._ts(y, m), "absa", "cash_withdrawal", "debit", "", kind="draw",
                     frac=h["draw_rate"] / n_atm * (1.5 if overdraft else 1.0))

    # ---- walking events in time order ------------------------------------------------

    def _ref(self, channel, ts):
        rng = self.rng
        if channel == "absa":
            tail = "".join(REF_CHARS[i] for i in rng.integers(0, len(REF_CHARS), size=5))
            return f"FT{ts:%y%j}{tail}"
        if channel == "mtn":
            return str(rng.integers(10**10, 10**11))
        return f"MP{ts:%y%m%d}.{ts:%H%M}.{'ABCDEFGH'[rng.integers(8)]}{rng.integers(10000, 100000)}"

    def walk(self) -> dict:
        rng = self.rng
        bal = dict(self.opening)
        rows = {c: [] for c in self.channels}

        def record(channel, ts, desc, category, direction, amount, counterparty, pair=None,
                   ref=None):
            bal[channel] += amount if direction == "credit" else -amount
            rows[channel].append({
                "ts": ts, "description": desc, "reference": ref or self._ref(channel, ts),
                "direction": direction, "amount": round(amount, 2),
                "balance": round(bal[channel], 2), "true_category": category,
                "counterparty": counterparty, "pair_ref": pair,
            })

        for ev in sorted(self.events, key=lambda e: (e["ts"], e["seq"])):
            ch, kind, ts = ev["channel"], ev["kind"], ev["ts"]
            avail = bal[ch] - self.floor[ch]
            if kind == "sweep":
                amount = _floor10(ev["frac"] * bal[ch])
                if amount < 200:
                    continue
                ref = self._ref(ch, ts)
                wallet = WALLET_NAMES[ch]
                record(ch, ts, f"Transfer to Bank ABSA {self.p['channels']['absa']}",
                       "own_account_transfer", "debit", amount, "Own Absa account", ref, ref)
                record("absa", ts + timedelta(minutes=int(rng.integers(1, 6))),
                       f"{wallet} MOMO TRF {self.p['channels'][ch]}", "own_account_transfer",
                       "credit", amount, f"Own {wallet} wallet", ref, ref)
                continue
            if kind == "draw":
                amount = _floor10(ev["frac"] * avail)
                if amount < 50:
                    continue
                if ch == "absa":
                    desc = f"ATM WDL {self.p['town'].upper()}"
                else:
                    desc = f"Cash Out via Agent {rng.choice(self.agents)}"
                record(ch, ts, desc, "cash_withdrawal", "debit", amount, "Cash")
                if ch != "absa":
                    fee = min(round(max(2.5, amount * 0.015), 2), bal[ch])
                    if fee > 0:
                        record(ch, ts + timedelta(seconds=5), "Cash Out Fee", "bank_charges",
                               "debit", fee, ch.upper())
                continue
            if kind == "od_interest":
                if bal["absa"] >= 0:
                    continue
                amount = round(0.025 * -bal["absa"], 2)
            else:
                amount = ev["amount"]
            if ev["direction"] == "debit" and kind != "charge" and kind != "od_interest":
                if amount > avail:
                    amount = _floor10(avail * 0.95)
                if amount < 10:
                    continue
            record(ch, ts, ev["desc"], ev["category"], ev["direction"], amount,
                   ev["counterparty"])
        return rows


def build_ledgers(entry: dict, rng: np.random.Generator) -> dict:
    builder = LedgerBuilder(entry, rng)
    builder.plan()
    rows = builder.walk()
    client = entry["profile"]["client_id"]
    for channel, ledger in rows.items():
        for n, row in enumerate(ledger, start=1):
            row["row_id"] = f"{client}-{channel.upper()}-{n:04d}"
            row["true_amount"] = row["amount"]
            row["tampered"] = False
            row["injection"] = False
    pairs = {}
    for channel, ledger in rows.items():
        for row in ledger:
            if row["pair_ref"]:
                pairs.setdefault(row["pair_ref"], {})[channel] = row["row_id"]
    transfer_pairs = [sorted(p.values(), key=lambda r: "ABSA" in r) for p in pairs.values()]
    return {
        "ledgers": rows,
        "opening": builder.opening,
        "monthly_takings": builder.monthly_takings,
        "transfer_pairs": transfer_pairs,
        "dominant_customer": builder.dominant if "dominant_customer" in builder.findings else None,
    }
