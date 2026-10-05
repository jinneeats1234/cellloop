from pathlib import Path

import numpy as np

from app.services.impedance import analyze_eis, analyze_iv, synth_eis, synth_iv
from app.services.parsing import parse_file
from app.services.recommender import NumpyGP

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def test_eis_analysis_recovers_asr():
    eis = synth_eis(r_ohm_asr=0.10, r_pol_asr=0.25, area=1.0, n=80)
    out = analyze_eis(eis, active_area_cm2=1.0)
    assert abs(out["ohmic_asr_ohm_cm2"] - 0.10) / 0.10 < 0.25
    assert abs(out["asr_ohm_cm2"] - 0.35) / 0.35 < 0.15


def test_iv_analysis():
    out = analyze_iv(synth_iv(asr=0.3, ocv=1.08))
    assert out["ocv_v"] == 1.08
    assert 0.5 < out["peak_power_density_w_cm2"] < 1.2


def test_parse_eis_export_with_metadata_preamble():
    parsed = parse_file("eis_export_ridgeline.csv", (SAMPLES / "eis_export_ridgeline.csv").read_bytes())
    assert parsed.eis_data is not None
    assert len(parsed.eis_data["freq_hz"]) == 40
    assert all(z <= 0.001 for z in parsed.eis_data["z_imag"])  # capacitive convention
    assert "Crofer 22 APU" in parsed.text


def test_numpy_gp_interpolates_and_quantifies_uncertainty():
    rng = np.random.default_rng(1)
    U = rng.random((25, 2))
    y = np.sin(3 * U[:, 0]) + 0.5 * U[:, 1]
    gp = NumpyGP().fit(U, y)
    mu, sd = gp.predict(U[:5])
    assert np.allclose(mu, y[:5], atol=0.1)
    _, sd_far = gp.predict(np.array([[3.0, 3.0]]))  # far outside the data
    assert sd_far[0] > 5 * sd.mean()
