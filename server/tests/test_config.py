from aigm.config import Settings


def test_the_gm_thinks_at_low_effort_by_default(monkeypatch):
    monkeypatch.delenv("AIGM_EFFORT", raising=False)
    assert Settings(_env_file=None).effort == "low"


def test_effort_can_be_raised_or_left_to_the_model(monkeypatch):
    monkeypatch.setenv("AIGM_EFFORT", "high")
    assert Settings(_env_file=None).effort == "high"
    monkeypatch.setenv("AIGM_EFFORT", "")
    assert Settings(_env_file=None).effort is None
