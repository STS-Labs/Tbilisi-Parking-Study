"""Pipeline plumbing that only misbehaves on the *second* run.

The boundary is cached to GeoJSON so the 14-second area-assembly pass runs once.
Reading it back has to survive the driver's own type inference, which is exactly
the kind of thing that passes on a clean checkout and fails a day later.
"""
import pytest
from shapely.geometry import box

from efficientroute import pipeline


def test_boundary_survives_a_geojson_round_trip(tmp_path):
    polygon = box(44.70, 41.70, 44.80, 41.80)
    tags = {"name": "თბილისი", "name:en": "Tbilisi", "admin_level": "4"}
    path = tmp_path / "boundary.geojson"

    pipeline.save_boundary(path, 1996871, polygon, tags)
    relation_id, geometry, restored = pipeline.load_boundary(path)

    assert relation_id == 1996871
    assert isinstance(relation_id, int)
    assert isinstance(restored, dict), "tags must come back as a mapping, not a raw string"
    assert restored["admin_level"] == "4"
    assert restored["name"] == "თბილისი"
    assert geometry.equals(polygon)


def test_cached_boundary_is_reused_without_touching_the_pbf(tmp_path):
    polygon = box(44.70, 41.70, 44.80, 41.80)
    path = tmp_path / "boundary.geojson"
    pipeline.save_boundary(path, 42, polygon, {"admin_level": "4"})

    # a PBF path that does not exist: reaching for it would raise
    relation_id, _, _ = pipeline.ensure_boundary(tmp_path / "missing.osm.pbf", path)
    assert relation_id == 42


def test_stage0_invalidates_the_stage2_artifact_it_overwrote(tmp_path, monkeypatch):
    """Rebuilding the arcs layer removes the Stage 2 columns, so the Stage 2
    artifact that described them must not be left behind claiming otherwise."""
    from efficientroute import config as C
    from efficientroute import pipeline

    path = tmp_path / "02-time-model.json"
    path.write_text("{}")
    monkeypatch.setattr(C, "TIME_MODEL_JSON", path)

    pipeline._invalidate_stage2()
    assert not path.exists()


def test_invalidating_a_stage2_artifact_that_is_not_there_is_not_an_error(tmp_path, monkeypatch):
    from efficientroute import config as C
    from efficientroute import pipeline

    monkeypatch.setattr(C, "TIME_MODEL_JSON", tmp_path / "absent.json")
    pipeline._invalidate_stage2()


def test_rebuild_applies_the_stage2_columns_only_when_the_model_is_on_disk(tmp_path, monkeypatch):
    """The rebuild has to track whichever stage the derived directory has reached."""
    from efficientroute import config as C
    from efficientroute import pipeline, timemodel

    monkeypatch.setattr(C, "TIME_MODEL_JSON", tmp_path / "absent.json")
    assert not C.TIME_MODEL_JSON.exists()

    seen = {}

    def fake_augment(table, model=None):
        seen["called"] = True
        return table

    monkeypatch.setattr(timemodel, "augment", fake_augment)
    monkeypatch.setattr(pipeline.network, "build_arc_table", lambda *a, **k: "table")
    monkeypatch.setattr(pipeline.X, "load_extract", lambda *a, **k: _FakeExtract())
    monkeypatch.setattr(pipeline, "ensure_dem", lambda *a, **k: (None, []))

    assert pipeline.rebuild_arc_table() == "table"
    assert "called" not in seen


class _FakeExtract:
    class clip:
        bounds = (44.0, 41.0, 45.0, 42.0)


def test_the_stage3_report_can_be_rewritten_without_resolving(tmp_path, monkeypatch):
    """Twelve minutes of exact solving must not be the price of rewording a line."""
    import json

    from efficientroute import config as C
    from efficientroute import pipeline, report03

    artifact = tmp_path / "03-bounds.json"
    artifact.write_text(json.dumps({"variants": [], "sentinel": True}))
    written = {}

    monkeypatch.setattr(C, "BOUNDS_JSON", artifact)
    monkeypatch.setattr(C, "BOUNDS_REPORT_MD", tmp_path / "03-bounds.md")
    monkeypatch.setattr(report03, "write", lambda a, path: written.update(a) or path)

    payload = pipeline.rewrite_stage3_report()
    assert payload["sentinel"] is True
    assert written["sentinel"] is True, "the report is rendered from the artifact, not re-solved"


def test_rewriting_without_an_artifact_is_a_clear_error(tmp_path, monkeypatch):
    from efficientroute import config as C
    from efficientroute import pipeline

    monkeypatch.setattr(C, "BOUNDS_JSON", tmp_path / "absent.json")
    with pytest.raises(FileNotFoundError, match="run `make stage3`"):
        pipeline.rewrite_stage3_report()
