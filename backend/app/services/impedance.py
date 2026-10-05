"""Electrochemical analysis of raw curves.

ASR from EIS: ohmic resistance is the high-frequency real-axis intercept; total resistance
is the low-frequency intercept. Multiplying by the active area gives Ω·cm². When
impedance.py is installed an R0-p(R1,CPE1)-p(R2,CPE2) equivalent circuit is fit instead.
"""

from typing import Any

import numpy as np


def _intercept_at_zero_imag(z_re: np.ndarray, z_im: np.ndarray) -> float:
    """Z' where -Z'' crosses zero, scanning from the first point.

    Interpolates when the spectrum crosses the real axis; otherwise (the arc is still open
    at the frequency limit) extrapolates the first three points to -Z'' = 0.
    """
    neg = -z_im
    for i in range(len(neg) - 1):
        if neg[i] == 0:
            return float(z_re[i])
        if neg[i] * neg[i + 1] < 0:
            t = neg[i] / (neg[i] - neg[i + 1])
            return float(z_re[i] + t * (z_re[i + 1] - z_re[i]))
    if len(neg) >= 3 and np.ptp(neg[:3]) > 0:
        _, intercept = np.polyfit(neg[:3], z_re[:3], 1)  # Z' as a linear function of -Z''
        # Only extrapolate outward (away from the rest of the spectrum), by at most the spectrum's span.
        outward = np.sign(z_re[0] - z_re[-1])
        step = float(np.clip((intercept - z_re[0]) * outward, 0.0, abs(z_re[-1] - z_re[0])))
        return max(0.0, float(z_re[0] + outward * step))
    return float(z_re[0])


def analyze_eis(eis: dict[str, list[float]], active_area_cm2: float | None) -> dict[str, Any]:
    f = np.asarray(eis["freq_hz"], dtype=float)
    zr = np.asarray(eis["z_real"], dtype=float)
    zi = np.asarray(eis["z_imag"], dtype=float)
    order = np.argsort(-f)  # high -> low frequency
    f, zr, zi = f[order], zr[order], zi[order]

    r_ohm = _intercept_at_zero_imag(zr, zi)
    r_total = _intercept_at_zero_imag(zr[::-1], zi[::-1])
    method = "real-axis intercepts"

    fit = _try_circuit_fit(f, zr, zi)
    if fit:
        r_ohm, r_total, method = fit["r0"], fit["r0"] + fit["r1"] + fit["r2"], "equivalent-circuit fit (impedance.py)"

    result: dict[str, Any] = {
        "method": method,
        "r_ohmic_ohm": round(r_ohm, 5),
        "r_polarization_ohm": round(r_total - r_ohm, 5),
        "r_total_ohm": round(r_total, 5),
        "summit_freq_hz": float(f[int(np.argmin(zi))]),
    }
    if active_area_cm2:
        result.update(
            ohmic_asr_ohm_cm2=round(r_ohm * active_area_cm2, 4),
            polarization_asr_ohm_cm2=round((r_total - r_ohm) * active_area_cm2, 4),
            asr_ohm_cm2=round(r_total * active_area_cm2, 4),
        )
    return result


def _try_circuit_fit(f: np.ndarray, zr: np.ndarray, zi: np.ndarray) -> dict[str, float] | None:
    try:
        from impedance.models.circuits import CustomCircuit  # type: ignore
    except ImportError:
        return None
    try:
        r0 = float(zr.min())
        span = float(zr.max() - zr.min()) or 1e-3
        circuit = CustomCircuit("R0-p(R1,CPE1)-p(R2,CPE2)",
                                initial_guess=[r0, span / 2, 1e-2, 0.9, span / 2, 1.0, 0.8])
        circuit.fit(f, zr + 1j * zi)
        p = circuit.parameters_
        return {"r0": float(p[0]), "r1": float(p[1]), "r2": float(p[4])}
    except Exception:  # fitting can fail on noisy data; intercepts are the robust fallback
        return None


def analyze_iv(iv: dict[str, list[float]]) -> dict[str, Any]:
    j = np.asarray(iv["current_density_a_cm2"], dtype=float)
    v = np.asarray(iv["voltage_v"], dtype=float)
    p = j * v
    k = int(np.argmax(p))
    out: dict[str, Any] = {"peak_power_density_w_cm2": round(float(p[k]), 4), "ocv_v": round(float(v[np.argmin(j)]), 4)}
    if len(j) >= 3:  # slope of the quasi-linear region approximates the DC ASR
        mid = slice(len(j) // 4, max(len(j) // 4 + 2, 3 * len(j) // 4))
        slope = np.polyfit(j[mid], v[mid], 1)[0]
        out["iv_asr_ohm_cm2"] = round(float(-slope), 4)
    return out


def synth_eis(r_ohm_asr: float, r_pol_asr: float, area: float, n: int = 50) -> dict[str, list[float]]:
    """Two-arc (anode + cathode) synthetic spectrum; used by the seed script and tests."""
    f = np.logspace(5, -1, n)
    w = 2 * np.pi * f
    r0, r1, r2 = r_ohm_asr / area, 0.35 * r_pol_asr / area, 0.65 * r_pol_asr / area
    z = r0 + r1 / (1 + (1j * w * r1 * 2e-4) ** 0.9) + r2 / (1 + (1j * w * r2 * 5e-2) ** 0.85)
    return {"freq_hz": f.round(4).tolist(), "z_real": z.real.round(6).tolist(), "z_imag": z.imag.round(6).tolist()}


def synth_iv(asr: float, ocv: float = 1.08, n: int = 20) -> dict[str, list[float]]:
    j = np.linspace(0, min(2.5, 0.75 / asr), n)
    v = ocv - asr * j - 0.03 * np.log1p(8 * j) - 0.02 * (j / j.max()) ** 6
    return {"current_density_a_cm2": j.round(4).tolist(), "voltage_v": v.round(4).tolist()}
