"""Data model for the firm's editable track record (clients / projects).

The decks no longer hard-code their experience slides; they read from this
store. Each project carries a *short* description (used by the Custom Offer) and
a *long* description (used by the General Description), each in both languages,
plus the client name (also bilingual, since some clients are public institutions
whose names translate, e.g. "Government of the Republic of Moldova" ->
"Guvernul Republicii Moldova").
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

# The 15 experience categories, in display order. `id` is a stable internal key
# (never shown); `name` is what renders on the slides / dashboard.
CATEGORIES: list[dict] = [
    {"id": "ma",              "name": {"en": "Mergers & Acquisitions",
                                       "ro": "Fuziuni și achiziții"}},
    {"id": "competition",     "name": {"en": "Competition Law",
                                       "ro": "Dreptul concurenței"}},
    {"id": "banking",         "name": {"en": "Guarantees, Security, Regulatory & Banking",
                                       "ro": "Garanții, Reglementare și domeniul bancar"}},
    {"id": "treasury",        "name": {"en": "Treasury, Cash Management & Foreign Exchange",
                                       "ro": "Trezorerie, Managementul Numerarului și Schimb Valutar"}},
    {"id": "grc",             "name": {"en": "Governance, Risk & Compliance",
                                       "ro": "Guvernanță, Risc și Conformitate"}},
    {"id": "sanctions",       "name": {"en": "Sanctions Compliance",
                                       "ro": "Conformitatea cu Sancțiunile"}},
    {"id": "regulatory",      "name": {"en": "Regulatory & Product Compliance",
                                       "ro": "Reglementări și Conformitatea Produselor"}},
    {"id": "public_policy",   "name": {"en": "Public Policy, Legislative Drafting & Regulatory Frameworks",
                                       "ro": "Politici Publice, Elaborare Legislativă și Cadre de Reglementare"}},
    {"id": "data_protection", "name": {"en": "Data Protection, Privacy & Digital Compliance",
                                       "ro": "Protecția Datelor, Confidențialitatea și Conformitatea Digitală"}},
    {"id": "energy",          "name": {"en": "Energy Sector",
                                       "ro": "Sectorul Energetic"}},
    {"id": "distribution",    "name": {"en": "Distribution, Dealer & After-Sales Frameworks",
                                       "ro": "Cadre de Distribuție, Dealer și After-Sales"}},
    {"id": "contractual",     "name": {"en": "Current Contractual Practice",
                                       "ro": "Practica contractuală curentă"}},
    {"id": "hr_labour",       "name": {"en": "HR / Labour Legal Framework",
                                       "ro": "Cadrul juridic pentru resurse umane/muncă"}},
    {"id": "disputes",        "name": {"en": "Dispute Resolution & Regulatory Risk Management",
                                       "ro": "Soluționarea Disputelor și Gestionarea Riscului de Reglementare"}},
    {"id": "ip",              "name": {"en": "Intellectual Property – Administration & Enforcement",
                                       "ro": "Proprietate Intelectuală – Administrare și Aplicare"}},
]

CATEGORY_IDS = {c["id"] for c in CATEGORIES}


def _now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _bilingual(en: str = "", ro: str = "") -> dict:
    return {"en": (en or "").strip(), "ro": (ro or "").strip()}


@dataclass
class Project:
    category: str                                   # one of CATEGORY_IDS
    client: dict = field(default_factory=_bilingual)   # {en, ro}
    short: dict = field(default_factory=_bilingual)    # {en, ro} — Custom Offer
    long: dict = field(default_factory=_bilingual)     # {en, ro} — General Description
    order: int = 0
    active: bool = True
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    updated_at: str = field(default_factory=_now)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Project":
        return Project(
            id=d.get("id") or uuid.uuid4().hex,
            category=d["category"],
            client=_bilingual(**(d.get("client") or {})),
            short=_bilingual(**(d.get("short") or {})),
            long=_bilingual(**(d.get("long") or {})),
            order=int(d.get("order", 0)),
            active=bool(d.get("active", True)),
            updated_at=d.get("updated_at") or _now(),
        )


def empty_db() -> dict:
    """A fresh store: the 15 categories, no projects yet."""
    return {"version": 1, "categories": CATEGORIES, "projects": []}
