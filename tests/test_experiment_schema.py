"""Experiment schema tests. All experiments here are test fixtures only."""
import copy
import dataclasses
import json

import pytest

from lunarmatch.experiments import schema as sc

FIXTURE = {   # placeholder content; not a real or approved experiment
    "experiment_id": "EXP-900",
    "name": "Fixture experiment",
    "status": "draft",
    "version": "0.1",
    "objective": "Test fixture.",
    "related_failure_modes": ["fixture_mode"],
    "required_features": ["feature_a", "feature_b"],
    "optional_features": ["feature_c"],
    "default_weights": {"feature_a": 0.6, "feature_b": 0.4},
    "matching_algorithm": "fixture_matcher",
    "limitations": ["Fixture only."],
}


def exp(**changes):
    d = copy.deepcopy(FIXTURE)
    d.update(changes)
    return d


def catalog(*exps):
    return {"schema_version": "1", "experiments": list(exps)}


def write(tmp_path, data):
    p = tmp_path / "catalog.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# ---------------------------------------------------------------- shipped catalog
def test_shipped_catalog_is_empty_and_has_no_approved():
    exps = sc.load_catalog()
    assert exps == []
    assert sc.approved_experiments(exps) == []
    raw = json.loads(sc.DEFAULT_CATALOG.read_text(encoding="utf-8"))
    assert raw == {"schema_version": "1", "experiments": []}


# ---------------------------------------------------------------- loading
def test_load_and_filter_approved(tmp_path):
    p = write(tmp_path, catalog(
        exp(experiment_id="EXP-901", status="draft"),
        exp(experiment_id="EXP-902", status="approved"),
        exp(experiment_id="EXP-903", status="deprecated"),
    ))
    exps = sc.load_catalog(p)
    assert [e.status for e in exps] == ["draft", "approved", "deprecated"]
    assert [e.experiment_id for e in sc.approved_experiments(exps)] == ["EXP-902"]


def test_roundtrip_preserves_fields_and_status(tmp_path):
    e = sc.Experiment.from_dict(FIXTURE)
    assert e.to_dict() == FIXTURE
    assert e.status == "draft" and not e.is_approved


def test_experiment_is_frozen():
    e = sc.Experiment.from_dict(FIXTURE)
    with pytest.raises(dataclasses.FrozenInstanceError):
        e.status = "approved"


def test_minimal_draft_is_valid():
    d = {k: FIXTURE[k] for k in ("experiment_id", "name", "status", "version", "objective")}
    e = sc.Experiment.from_dict(d)
    assert e.required_features == () and e.default_weights == {}


# ---------------------------------------------------------------- validation
@pytest.mark.parametrize("bad", [
    exp(status="Approved"),
    exp(status="pending"),
    exp(experiment_id="EXP-1"),
    exp(experiment_id="exp-001"),
    exp(name=""),
    exp(version=1),
    exp(required_features="feature_a"),
    exp(required_features=["feature_a", ""]),
    exp(required_features=["feature_a", "feature_a"]),
    exp(optional_features=["feature_a"]),                      # both req & opt
    exp(default_weights={"feature_z": 1.0}),                   # undeclared
    exp(default_weights={"feature_a": -0.1}),
    exp(default_weights={"feature_a": float("nan")}),
    exp(default_weights={"feature_a": "0.5"}),
    exp(default_weights={"feature_a": True}),
    exp(default_weights=[0.5]),
    exp(approved_by="me"),                                     # unknown field
    exp(status="approved", required_features=[], optional_features=["feature_c"],
        default_weights={}),
    exp(status="approved", default_weights={}),
    exp(status="approved", matching_algorithm=""),
], ids=lambda d: next((f"{k}={d[k]!r}" for k in d if d[k] != FIXTURE.get(k)), "?"))
def test_invalid_experiments_rejected(bad):
    with pytest.raises(sc.ExperimentValidationError):
        sc.Experiment.from_dict(bad)


def test_missing_required_field():
    d = exp()
    del d["objective"]
    with pytest.raises(sc.ExperimentValidationError, match="objective"):
        sc.Experiment.from_dict(d)


@pytest.mark.parametrize("data", [
    [],
    {"experiments": []},                                  # no schema_version
    {"schema_version": "2", "experiments": []},
    {"schema_version": "1", "experiments": {}},
    catalog(exp(), exp()),                                # duplicate id
])
def test_invalid_catalogs_rejected(data):
    with pytest.raises(sc.ExperimentValidationError):
        sc.parse_catalog(data)


def test_invalid_json(tmp_path):
    p = tmp_path / "c.json"
    p.write_text("{not json", encoding="utf-8")
    with pytest.raises(sc.ExperimentValidationError, match="invalid JSON"):
        sc.load_catalog(p)
