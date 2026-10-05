""""Next experiment" recommender: Gaussian-process Bayesian optimization over cell design.

This is classical ML, deliberately not an LLM. A GP is fit to approved experiments
(design variables -> log ASR at the target operating temperature). Candidates are
ranked by Expected Improvement, which balances exploiting promising regions against
exploring uncertain ones, i.e. the most learning per (expensive) test. A batch is
built greedily with local penalization so suggestions are not near-duplicates.

Engines: BoTorch (SingleTaskGP + LogExpectedImprovement) when installed, otherwise a
built-in NumPy/SciPy GP with ARD RBF kernel fit by maximum marginal likelihood.
Every suggestion carries a 95% interval, a probability of beating the target and a
plain-language rationale generated from those numbers (not by an LLM).
"""

import logging
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy.optimize import minimize
from scipy.stats import norm, qmc
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.errors import ProcessingError
from ..core.validation import like_contains
from ..experiment_schema import DESIGN_SPACE, FIELDS_BY_KEY, OBJECTIVE_KEY
from ..models import Experiment, ExperimentStatus

settings = get_settings()
log = logging.getLogger(__name__)
KEYS = list(DESIGN_SPACE)
LO = np.array([DESIGN_SPACE[k][0] for k in KEYS])
HI = np.array([DESIGN_SPACE[k][1] for k in KEYS])
MIN_TRAINING = 6


def to_unit(x: np.ndarray) -> np.ndarray:
    return (x - LO) / (HI - LO)


def from_unit(u: np.ndarray) -> np.ndarray:
    return LO + u * (HI - LO)


@dataclass
class TrainingSet:
    X: np.ndarray       # raw design values (n, d)
    asr: np.ndarray     # (n,)
    codes: list[str]
    ids: list[str]
    excluded: int       # approved experiments lacking design variables / ASR / matching temperature


def load_training(db: Session, target_temp_c: float, temp_tolerance_c: float,
                  filters: dict[str, str] | None = None) -> TrainingSet:
    stmt = select(Experiment).where(Experiment.status == ExperimentStatus.approved.value)
    for key, value in (filters or {}).items():
        if value:
            stmt = stmt.where(getattr(Experiment, key).ilike(like_contains(value), escape="\\"))
    rows, codes, ids, ys, excluded = [], [], [], [], 0
    for e in db.scalars(stmt):
        vals = {k: getattr(e, k) for k in KEYS}
        if vals["coating_thickness_um"] is None and (e.coating_material or "").strip().lower() == "none":
            vals["coating_thickness_um"] = 0.0
        asr = getattr(e, OBJECTIVE_KEY)
        if (any(v is None for v in vals.values()) or not asr or asr <= 0 or e.operating_temp_c is None
                or abs(e.operating_temp_c - target_temp_c) > temp_tolerance_c):
            excluded += 1
            continue
        rows.append([vals[k] for k in KEYS])
        ys.append(asr)
        codes.append(e.code)
        ids.append(e.id)
    X = np.asarray(rows, dtype=float).reshape(-1, len(KEYS))
    return TrainingSet(X, np.asarray(ys, dtype=float), codes, ids, excluded)


# ---------------------------------------------------------------------------------
# Built-in GP (ARD squared-exponential, Gaussian noise, ML-II hyperparameters)
# ---------------------------------------------------------------------------------

class NumpyGP:
    name = "NumPy/SciPy Gaussian process (ARD RBF, ML-II)"

    def fit(self, U: np.ndarray, y: np.ndarray) -> "NumpyGP":
        self.U = U
        self.y_mean, self.y_std = float(y.mean()), float(y.std() or 1.0)
        self.ys = (y - self.y_mean) / self.y_std
        d = U.shape[1]
        rng = np.random.default_rng(0)
        best = None
        starts = [np.r_[np.log(np.full(d, 0.3)), 0.0, np.log(0.1)]]
        starts += [np.r_[rng.uniform(np.log(0.05), np.log(1.5), d), rng.uniform(-1, 1), rng.uniform(-5, -1)] for _ in range(4)]
        bounds = [(np.log(0.02), np.log(5.0))] * d + [(np.log(0.05), np.log(20.0)), (np.log(1e-4), np.log(1.0))]
        for x0 in starts:
            res = minimize(self._nlml, x0, method="L-BFGS-B", bounds=bounds)
            if best is None or res.fun < best.fun:
                best = res
        self._set(best.x)
        return self

    def _kernel(self, A: np.ndarray, B: np.ndarray, ls: np.ndarray, sf2: float) -> np.ndarray:
        diff = (A[:, None, :] - B[None, :, :]) / ls
        return sf2 * np.exp(-0.5 * np.sum(diff ** 2, axis=-1))

    def _nlml(self, theta: np.ndarray) -> float:
        d = self.U.shape[1]
        ls, sf2, sn2 = np.exp(theta[:d]), math.exp(theta[d]), math.exp(theta[d + 1])
        K = self._kernel(self.U, self.U, ls, sf2) + (sn2 + 1e-8) * np.eye(len(self.U))
        try:
            L = np.linalg.cholesky(K)
        except np.linalg.LinAlgError:
            return 1e10
        alpha = np.linalg.solve(L.T, np.linalg.solve(L, self.ys))
        return float(0.5 * self.ys @ alpha + np.log(np.diag(L)).sum() + 0.5 * len(self.ys) * math.log(2 * math.pi))

    def _set(self, theta: np.ndarray) -> None:
        d = self.U.shape[1]
        self.ls, self.sf2, self.sn2 = np.exp(theta[:d]), math.exp(theta[d]), math.exp(theta[d + 1])
        K = self._kernel(self.U, self.U, self.ls, self.sf2) + (self.sn2 + 1e-8) * np.eye(len(self.U))
        self.L = np.linalg.cholesky(K)
        self.alpha = np.linalg.solve(self.L.T, np.linalg.solve(self.L, self.ys))

    def predict(self, Uc: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        Ks = self._kernel(Uc, self.U, self.ls, self.sf2)
        mu = Ks @ self.alpha
        v = np.linalg.solve(self.L, Ks.T)
        var = np.clip(self.sf2 - np.sum(v ** 2, axis=0), 1e-12, None)
        return mu * self.y_std + self.y_mean, np.sqrt(var) * self.y_std

    def relevance(self) -> np.ndarray:
        r = 1.0 / self.ls
        return r / r.sum()


class BoTorchGP:
    name = "BoTorch SingleTaskGP + LogExpectedImprovement"

    def fit(self, U: np.ndarray, y: np.ndarray) -> "BoTorchGP":
        import torch
        from botorch.fit import fit_gpytorch_mll
        from botorch.models import SingleTaskGP
        from botorch.models.transforms.outcome import Standardize
        from gpytorch.mlls import ExactMarginalLogLikelihood

        self.torch = torch
        tx = torch.tensor(U, dtype=torch.double)
        ty = torch.tensor(y, dtype=torch.double).unsqueeze(-1)
        self.model = SingleTaskGP(tx, ty, outcome_transform=Standardize(m=1))
        fit_gpytorch_mll(ExactMarginalLogLikelihood(self.model.likelihood, self.model))
        self.best_f = float(y.max())
        return self

    def predict(self, Uc: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        with self.torch.no_grad():
            post = self.model.posterior(self.torch.tensor(Uc, dtype=self.torch.double))
            return post.mean.squeeze(-1).numpy(), post.variance.clamp_min(1e-12).sqrt().squeeze(-1).numpy()

    def log_ei(self, Uc: np.ndarray) -> np.ndarray:
        from botorch.acquisition import LogExpectedImprovement

        acqf = LogExpectedImprovement(self.model, best_f=self.best_f)
        with self.torch.no_grad():
            return acqf(self.torch.tensor(Uc, dtype=self.torch.double).unsqueeze(1)).numpy()

    def relevance(self) -> np.ndarray:
        kernel = self.model.covar_module
        ls = getattr(kernel, "lengthscale", None)
        if ls is None:
            ls = kernel.base_kernel.lengthscale
        r = 1.0 / ls.detach().numpy().ravel()
        return r / r.sum()


def _make_model() -> Any:
    try:
        import botorch  # noqa: F401
        return BoTorchGP()
    except ImportError:
        return NumpyGP()


def _fit_model(U: np.ndarray, y: np.ndarray) -> Any:
    """Fit BoTorch if available, falling back to the built-in GP if BoTorch fails numerically."""
    model = _make_model()
    try:
        return model.fit(U, y)
    except Exception as exc:  # BoTorch/GPyTorch can raise many numerical error types
        if isinstance(model, NumpyGP):
            raise ProcessingError(
                "The model couldn't be fitted to the current data (it may contain duplicate or "
                "contradictory results). Check recent approvals or narrow the filters.",
                code="model_fit_failed",
            ) from exc
        log.warning("BoTorch fit failed (%s); falling back to the built-in GP", exc)
    try:
        return NumpyGP().fit(U, y)
    except Exception as exc:
        raise ProcessingError(
            "The model couldn't be fitted to the current data. Check recent approvals or narrow the filters.",
            code="model_fit_failed",
        ) from exc


def expected_improvement(mu: np.ndarray, sd: np.ndarray, best: float) -> np.ndarray:
    z = (mu - best) / sd
    return (mu - best) * norm.cdf(z) + sd * norm.pdf(z)


# ---------------------------------------------------------------------------------
# Recommendation
# ---------------------------------------------------------------------------------

def _fmt(key: str, v: float) -> str:
    spec = FIELDS_BY_KEY[key]
    return f"{v:.3g} {spec.unit or ''}".strip()


def _rationale(*, params: dict[str, float], mean: float, lo: float, hi: float, p_target: float,
               uncertainty: str, nearest: dict, best: dict, relevance: dict[str, float], target: float) -> str:
    parts = [f"Expected total ASR {mean:.3f} Ω·cm² (95% interval {lo:.3f}–{hi:.3f})."]
    if uncertainty == "high":
        parts.append(
            f"Little data exists near this design: the closest tested cell, {nearest['code']}, is "
            f"{nearest['distance_pct']:.0f}% of the design range away. Testing here mainly buys information "
            "that sharpens the model's predictions everywhere else."
        )
    elif mean < best["asr"]:
        parts.append(
            f"The model expects this to improve on the current best ({best['code']}, {best['asr']:.3f} Ω·cm²) "
            "and is reasonably confident about it, so this is a targeted exploitation step."
        )
    else:
        parts.append("It balances a promising predicted ASR against moderate uncertainty.")
    best_params = best["params"]
    changes = sorted(
        ((relevance[k] * abs(params[k] - best_params[k]) / (DESIGN_SPACE[k][1] - DESIGN_SPACE[k][0]), k) for k in KEYS),
        reverse=True,
    )[:2]
    diffs = [
        f"{FIELDS_BY_KEY[k].label.lower()} {_fmt(k, best_params[k])} → {_fmt(k, params[k])}"
        for score, k in changes if score > 0.005
    ]
    if diffs:
        parts.append(f"Main changes vs. {best['code']}: " + "; ".join(diffs) + ".")
    parts.append(f"Estimated chance of meeting the {target:.2f} Ω·cm² target: {p_target:.0%}.")
    return " ".join(parts)


def _space_filling(n: int, training: TrainingSet, reason: str) -> dict[str, Any]:
    sampler = qmc.Sobol(d=len(KEYS), scramble=True, seed=7)
    U = sampler.random(max(8, 2 ** math.ceil(math.log2(n))))[:n]
    X = from_unit(U)
    return {
        "mode": "exploration",
        "engine": "Sobol space-filling design",
        "message": reason,
        "n_training": len(training.asr),
        "n_excluded": training.excluded,
        "best_observed": None,
        "feature_relevance": [],
        "candidates": [
            {"rank": i + 1, "params": {k: round(float(x[j]), 2) for j, k in enumerate(KEYS)},
             "predicted_asr": None, "ci95": None, "p_beats_target": None, "uncertainty": "unknown",
             "acquisition": None, "nearest_experiment": None,
             "rationale": "Space-filling design point: chosen to cover the design space evenly so the model can "
                          "learn which variables matter. No prediction is made until enough data exists."}
            for i, x in enumerate(X)
        ],
    }


def recommend(db: Session, *, n: int = 5, target_temp_c: float | None = None, temp_tolerance_c: float = 25.0,
              target_asr: float | None = None, filters: dict[str, str] | None = None, seed: int = 0) -> dict[str, Any]:
    target_temp_c = target_temp_c or settings.target_operating_temp_c
    target_asr = target_asr or settings.target_asr_ohm_cm2
    tr = load_training(db, target_temp_c, temp_tolerance_c, filters)
    if len(tr.asr) < MIN_TRAINING:
        return _space_filling(n, tr, f"Only {len(tr.asr)} approved experiments with complete design variables and an "
                                     f"ASR near {target_temp_c:.0f} °C (need {MIN_TRAINING}). Showing a space-filling "
                                     "design to bootstrap the model instead of predictions.")

    U = to_unit(tr.X)
    y = -np.log(tr.asr)  # maximize -log(ASR): ASR is positive and spans orders of magnitude
    model = _fit_model(U, y)
    best_y = float(y.max())
    best_idx = int(np.argmax(y))

    cand = qmc.Sobol(d=len(KEYS), scramble=True, seed=seed).random(4096)
    mu, sd = model.predict(cand)
    if isinstance(model, BoTorchGP):
        acq = np.exp(model.log_ei(cand))
    else:
        acq = expected_improvement(mu, sd, best_y)

    relevance_arr = model.relevance()
    relevance = {k: float(relevance_arr[i]) for i, k in enumerate(KEYS)}
    prior_sd = float(np.std(y)) or 1.0
    penalty_len = 0.15

    picks: list[int] = []
    work = acq.copy()
    for _ in range(n):
        i = int(np.argmax(work))
        if work[i] <= 0 and picks:
            break
        picks.append(i)
        d2 = np.sum((cand - cand[i]) ** 2, axis=1)
        work = work * (1 - np.exp(-d2 / (2 * penalty_len ** 2)))

    best = {"code": tr.codes[best_idx], "id": tr.ids[best_idx], "asr": float(tr.asr[best_idx]),
            "params": {k: float(tr.X[best_idx, j]) for j, k in enumerate(KEYS)}}
    log_target = -math.log(target_asr)
    out = []
    for rank, i in enumerate(picks, start=1):
        params = {k: round(float(v), 2) for k, v in zip(KEYS, from_unit(cand[i]))}
        m, s = float(mu[i]), float(sd[i])
        mean, lo, hi = math.exp(-m), math.exp(-(m + 1.96 * s)), math.exp(-(m - 1.96 * s))
        p_target = float(norm.cdf((m - log_target) / s))
        dists = np.sqrt(np.sum((U - cand[i]) ** 2, axis=1)) / math.sqrt(len(KEYS))
        j = int(np.argmin(dists))
        nearest = {"code": tr.codes[j], "id": tr.ids[j], "asr": float(tr.asr[j]),
                   "distance_pct": round(float(dists[j]) * 100, 1)}
        ratio = s / prior_sd
        uncertainty = "high" if ratio > 0.6 else "medium" if ratio > 0.3 else "low"
        out.append({
            "rank": rank, "params": params,
            "predicted_asr": round(mean, 4), "ci95": [round(lo, 4), round(hi, 4)],
            "p_beats_target": round(p_target, 3), "uncertainty": uncertainty,
            "acquisition": float(acq[i]), "nearest_experiment": nearest,
            "rationale": _rationale(params=params, mean=mean, lo=lo, hi=hi, p_target=p_target,
                                    uncertainty=uncertainty, nearest=nearest, best=best,
                                    relevance=relevance, target=target_asr),
        })

    return {
        "mode": "bayesian_optimization",
        "engine": model.name,
        "message": None,
        "n_training": len(tr.asr),
        "n_excluded": tr.excluded,
        "target_asr": target_asr,
        "target_temp_c": target_temp_c,
        "best_observed": {"code": best["code"], "id": best["id"], "asr": best["asr"], "params": best["params"]},
        "feature_relevance": sorted(
            [{"key": k, "label": FIELDS_BY_KEY[k].label, "relevance": round(v, 3)} for k, v in relevance.items()],
            key=lambda r: -r["relevance"],
        ),
        "candidates": out,
    }


def similar_experiments(db: Session, params: dict[str, float], k: int = 5) -> list[dict[str, Any]]:
    """"Have we tried this before?" Nearest approved experiments in normalized design space."""
    rows = []
    for e in db.scalars(select(Experiment).where(Experiment.status == ExperimentStatus.approved.value)):
        vals = [getattr(e, key) for key in KEYS]
        known = [(i, v) for i, v in enumerate(vals) if v is not None and KEYS[i] in params]
        if len(known) < 3:
            continue
        d = math.sqrt(sum(((v - params[KEYS[i]]) / (HI[i] - LO[i])) ** 2 for i, v in known) / len(known))
        rows.append({"id": e.id, "code": e.code, "distance_pct": round(d * 100, 1), "asr_ohm_cm2": e.asr_ohm_cm2,
                     "operating_temp_c": e.operating_temp_c, "organization": e.organization})
    return sorted(rows, key=lambda r: r["distance_pct"])[:k]
