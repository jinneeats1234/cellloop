"""Populate a development database with a realistic synthetic MS-SOFC campaign.

    python -m app.scripts.seed            # create tables + seed if empty
    python -m app.scripts.seed --reset    # drop everything first

All organizations, people and results are fictional. Results come from a hidden
ground-truth function (below) so the recommender has real structure to learn.
"""

import argparse
import hashlib
import math
import os
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import select

from ..core import audit
from ..core.database import Base, SessionLocal, engine, init_db
from ..experiment_schema import completeness
from ..models import INTERNAL_ORG, Document, DocumentStatus, Experiment, ExperimentStatus, Role, User
from ..services import rag
from ..services.extraction import next_experiment_code, run_extraction
from ..services.impedance import synth_eis, synth_iv
from ..services.storage import get_storage

SAMPLES = Path(os.environ.get("CELLLOOP_SAMPLES_DIR", Path(__file__).resolve().parents[3] / "samples"))

USERS = [
    ("scientist@cellloop.dev", "Sam Rivera", Role.scientist, INTERNAL_ORG),
    ("lead@cellloop.dev", "Priya Natarajan", Role.leadership, INTERNAL_ORG),
    ("admin@cellloop.dev", "Alex Kim", Role.admin, INTERNAL_ORG),
    ("researcher@northgate.edu", "Jordan Okafor", Role.partner, "northgate-univ"),
    ("researcher@ridgeline-lab.org", "Casey Lindqvist", Role.partner, "ridgeline-lab"),
    ("researcher@lakeshore.edu", "Morgan Ellis", Role.partner, "lakeshore-univ"),
]
PARTNERS = {
    "northgate-univ": "Northgate University SOFC Characterization Lab",
    "ridgeline-lab": "Ridgeline National Laboratory, Electrochemistry Group",
    "lakeshore-univ": "Lakeshore University Materials Science Dept.",
}


def true_asr(p: dict, temp_c: float) -> tuple[float, float]:
    """Hidden ground truth -> (ohmic ASR, polarization ASR) in Ω·cm²."""
    ohm = 0.03 + 0.012 * p["electrolyte_thickness_um"] + 0.003 * p["coating_thickness_um"]
    pol = (0.08
           + 0.25 * ((p["sintering_temp_c"] - 1240) / 120) ** 2
           + 0.04 * ((p["cathode_thickness_um"] - 30) / 15) ** 2
           + 0.12 * math.exp(-p["coating_thickness_um"] / 4)
           + 0.03 * ((p["sintering_time_h"] - 2.5) / 2) ** 2
           + 0.02 * ((p["anode_thickness_um"] - 35) / 20) ** 2)
    arr = math.exp(9000 * (1 / (temp_c + 273.15) - 1 / 923.15))  # Ea ≈ 0.78 eV
    return ohm * arr * 0.8, pol * arr * 1.1


def _sample_design(rng: random.Random, progress: float) -> dict:
    """Early campaign: broad exploration. Later: drifts toward better (but not optimal) regions."""
    center = {"anode_thickness_um": 40, "electrolyte_thickness_um": 12 - 5 * progress,
              "cathode_thickness_um": 22 + 6 * progress, "sintering_temp_c": 1120 + 70 * progress,
              "sintering_time_h": 3.5, "coating_thickness_um": 2 + 3 * progress}
    spread = {"anode_thickness_um": 12, "electrolyte_thickness_um": 3, "cathode_thickness_um": 7,
              "sintering_temp_c": 60, "sintering_time_h": 1.2, "coating_thickness_um": 2}
    bounds = {"anode_thickness_um": (10, 60), "electrolyte_thickness_um": (3, 20), "cathode_thickness_um": (10, 50),
              "sintering_temp_c": (1000, 1350), "sintering_time_h": (0.5, 6), "coating_thickness_um": (0, 20)}
    out = {}
    for k, c in center.items():
        lo, hi = bounds[k]
        out[k] = round(min(hi, max(lo, rng.gauss(c, spread[k]))), 1)
    return out


def seed(reset: bool = False) -> None:
    if reset:
        Base.metadata.drop_all(engine)
    init_db()
    db = SessionLocal()
    try:
        if db.scalar(select(User).limit(1)):
            print("Database already seeded; use --reset to start over.")
            return
        users = {}
        for email, name, role, org in USERS:
            u = User(subject=f"dev|{email}", email=email, name=name, role=role.value, organization=org)
            db.add(u)
            users[email] = u
        db.flush()
        scientist = users["scientist@cellloop.dev"]

        rng = random.Random(42)
        storage = get_storage()
        start = date(2025, 10, 6)
        n_hist = 38
        cathodes = ["LSCF", "LSCF-GDC", "LSCF-GDC", "PrOx", "LSC"]
        orgs = list(PARTNERS)
        for i in range(n_hist):
            progress = i / (n_hist - 1)
            while True:
                p = _sample_design(rng, progress)
                temp = rng.choices([650, 650, 650, 650, 600, 700, 750], k=1)[0]
                r_ohm, r_pol = true_asr(p, temp)
                noise = math.exp(rng.gauss(0, 0.06))
                r_ohm, r_pol = r_ohm * noise, r_pol * noise
                if temp != 650 or r_ohm + r_pol > 0.33:  # campaign has not yet hit the 0.30 target at 650 °C
                    break
            org = orgs[i % 3]
            area = rng.choice([1.0, 1.0, 2.0, 0.5])
            test_day = start + timedelta(days=int(i * 9 + rng.randint(0, 4)))
            submitted = datetime.combine(test_day + timedelta(days=rng.randint(3, 10)), datetime.min.time(),
                                         tzinfo=timezone.utc) + timedelta(hours=9)
            # Before CellLoop, partner results took weeks to become structured records; recent ones < 48 h.
            lag = timedelta(days=rng.randint(12, 35)) if i < 26 else timedelta(hours=rng.randint(4, 40))
            asr = round(r_ohm + r_pol, 4)
            fields = dict(
                cell_id=f"{org[:2].upper()}-MS-{100 + i}", lab_name=PARTNERS[org],
                operator=None if rng.random() < 0.2 else rng.choice(["J. Okafor", "C. Lindqvist", "M. Ellis", "R. Tan"]),
                test_date=test_day, support_alloy=rng.choice(["Ferritic stainless 430L", "Ferritic stainless 430L", "Crofer 22 APU"]),
                anode_composition=rng.choice(["Ni-YSZ 60:40 wt%", "Ni-ScSZ"]), electrolyte_composition="8YSZ",
                cathode_composition=rng.choice(cathodes), active_area_cm2=area,
                sintering_atmosphere=None if rng.random() < 0.1 else "reducing (2% H2/Ar)",
                coating_material="none" if p["coating_thickness_um"] < 0.5 else "MnCo2O4 spinel",
                operating_temp_c=float(temp), fuel_composition="97% H2 / 3% H2O", oxidant="air",
                asr_ohm_cm2=asr, ohmic_asr_ohm_cm2=round(r_ohm, 4), polarization_asr_ohm_cm2=round(r_pol, 4),
                peak_power_density_w_cm2=round(min(1.6, 0.27 / asr), 3), ocv_v=round(rng.uniform(1.05, 1.11), 3),
                degradation_pct_per_khr=round(rng.uniform(0.6, 4.5), 2),
                thermal_cycles=rng.choice([None, 10, 25, 50, 100]),
                **p,
            )
            if rng.random() < 0.08:
                fields["cathode_thickness_um"] = None  # some legacy records lost metadata
            e = Experiment(code=next_experiment_code(db), organization=org, status=ExperimentStatus.approved.value,
                           source="extracted", submitted_at=submitted, reviewed_at=submitted + lag,
                           reviewed_by_id=scientist.id, eis_data=synth_eis(r_ohm, r_pol, area),
                           iv_data=synth_iv(asr, fields["ocv_v"]), **fields)
            e.completeness, _ = completeness(e.field_values())
            db.add(e)
            db.flush()
            rag.index_experiment(db, e)
        db.commit()

        # Internal reports for cited Q&A.
        for path in sorted((SAMPLES / "internal_reports").glob("*.md")):
            data = path.read_bytes()
            doc = Document(organization=INTERNAL_ORG, kind="internal_report", title=path.stem.replace("_", " "),
                           filename=path.name, content_type="text/markdown", size_bytes=len(data),
                           sha256=hashlib.sha256(data).hexdigest(), storage_key="",
                           uploaded_by_id=scientist.id, status=DocumentStatus.indexed.value,
                           extracted_text=data.decode())
            db.add(doc)
            db.flush()
            doc.storage_key = f"{INTERNAL_ORG}/{doc.id}/{path.name}"
            storage.put(doc.storage_key, data, doc.content_type)
            rag.index_document(db, doc)
        db.commit()

        # Fresh partner submissions waiting in the review queue (run through the extraction pipeline).
        pending = [("northgate-univ", "researcher@northgate.edu", SAMPLES / "partner_report_northgate.txt"),
                   ("ridgeline-lab", "researcher@ridgeline-lab.org", SAMPLES / "eis_export_ridgeline.csv")]
        for org, email, path in pending:
            data = path.read_bytes()
            doc = Document(organization=org, kind="partner_report", title=path.stem.replace("_", " "),
                           filename=path.name, content_type="text/plain", size_bytes=len(data),
                           sha256=hashlib.sha256(data).hexdigest(), storage_key="",
                           uploaded_by_id=users[email].id)
            db.add(doc)
            db.flush()
            doc.storage_key = f"{org}/{doc.id}/{path.name}"
            storage.put(doc.storage_key, data, doc.content_type)
            audit.record(db, actor=users[email], action="upload", entity_type="document", entity_id=doc.id,
                         organization=org, details={"filename": path.name, "kind": "partner_report"})
            db.commit()
            run_extraction(doc.id)

        print(f"Seeded {len(USERS)} users, {n_hist} approved experiments, internal reports and 2 pending submissions.")
        print("Dev logins: " + ", ".join(e for e, *_ in USERS))
    finally:
        db.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    seed(ap.parse_args().reset)
