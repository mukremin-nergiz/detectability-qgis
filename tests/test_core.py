"""The plugin's calculation layer, without QGIS. With any Python from 3.9 and NumPy:

    python -m pytest tests/test_core.py -q
"""
import ast
import math
import pathlib
import sys

HOME = pathlib.Path(__file__).resolve().parents[1]     # the folder that holds detectability_qgis/
ROOT = HOME.parent                                      # the Detectability project, when the plugin lives inside it
sys.path.insert(0, str(HOME))

from detectability_qgis import core  # noqa: E402

CAVITY = {"shape": "sphere", "depth_top": 15.0, "size": 20.0, "material": "air", "host": "limestone"}
WHERE = {"latitude": 39.75, "longitude": 37.02, "date": "2027-03-01"}


def test_the_bundled_library_gives_the_figure_the_site_checks_on_every_deploy():
    report = core.evaluate(CAVITY, {}, ["gravity"])
    a = report["results"][0]["assessment"]
    assert report["version"] == core.LIBRARY_VERSION and abs(a["peak"] - 114.1) < 0.05      # kontrol.sh: 114.1 µGal
    assert a["verdict"] == "clearly detectable"


def test_time_variation_is_added_to_the_site_noise_not_put_in_its_place():
    base = core.evaluate(CAVITY, WHERE, ["magnetic"])["results"][0]
    assert core.evaluate(CAVITY, WHERE, ["magnetic"], 0.0)["results"][0]["assessment"]["noise"] == base["assessment"]["noise"]
    for _, value in core.MAGNETIC_TIME_NT[1:]:
        r = core.evaluate(CAVITY, WHERE, ["magnetic"], value)["results"][0]
        assert r["field_noise_parts"]["site"] == 2.0 and r["field_noise_parts"]["time"] == value
        assert abs(r["field_noise"] - math.hypot(2.0, value)) < 1e-9
        assert abs(r["assessment"]["noise"] - math.hypot(r["instrument_noise"], r["field_noise"])) < 1e-9


def test_the_noise_choices_are_the_website_s():
    """Three places show these buttons: the tool's form, the limits chart and this panel. Same names, same figures."""
    web = ROOT / "web"
    if not (web / "templates" / "_noise.html").exists():
        return                                    # the plugin on its own, outside the project
    template = (web / "templates" / "_noise.html").read_text(encoding="utf-8")
    for name, value in core.GRAVITY_SITE_UGAL:
        assert f'data-gnoise="{value:g}"' in template and f">{name} {value:g}</button>" in template
    assert "Included in site noise (0)" in template and "Base readings" in template and "No correction" in template
    tree = ast.parse((web / "app.py").read_text(encoding="utf-8"))
    site = next(ast.literal_eval(n.value) for n in tree.body if isinstance(n, ast.Assign)
                and getattr(n.targets[0], "id", "") == "MAGNETIC_TIME_NOISE_NT")
    assert [v for _, v in core.MAGNETIC_TIME_NT] == [0.0, site["loop"], site["none"]]


def test_every_shape_and_method_offered_runs():
    for shape, _ in core.SHAPES:
        target = {"shape": shape, "depth_top": 3.0, "material": "air", "host": "limestone"}
        if shape in core.NEEDS_SIZE:
            target["size"] = 2.0
        if shape in core.NEEDS_BOTTOM:
            target["depth_bottom"] = 6.0
        report = core.evaluate(target, WHERE, [m for m, _ in core.METHODS])
        rows = core.rows(report)
        assert len(rows) == len(core.METHODS) and all(r["verdict"] for r in rows), shape


def test_resistivity_is_left_out_and_nothing_reaches_the_network():
    lib = HOME / "detectability_qgis" / "lib" / "detectability"
    assert "ert" not in [m for m, _ in core.METHODS]
    for path in list(lib.rglob("*.py")) + list((HOME / "detectability_qgis").glob("*.py")):
        source = path.read_text(encoding="utf-8")
        for word in ("urllib", "requests", "socket", "http.client", "subprocess", "pickle", "eval(", "exec("):
            assert word not in source, (path.name, word)


def test_stations_start_at_zero_and_stay_on_the_line():
    assert core.station_distances(100.0, 25.0) == [0.0, 25.0, 50.0, 75.0, 100.0]
    assert core.station_distances(99.0, 25.0) == [0.0, 25.0, 50.0, 75.0]          # no station beyond the end
    assert core.station_distances(3.0, 5.0) == [0.0]
    for bad in ((0.0, 5.0), (100.0, 0.0), (-1.0, 5.0)):
        try:
            core.station_distances(*bad)
        except ValueError:
            continue
        raise AssertionError(bad)
    try:
        core.station_distances(1e6, 0.01)
    except ValueError as error:
        assert "check the line" in str(error)
    else:
        raise AssertionError("a hundred million stations must be refused")


def test_the_layout_follows_the_recommended_method_and_says_when_nothing_is_detectable():
    report = core.evaluate(CAVITY, WHERE, ["gravity", "magnetic"])
    plan = core.layout(report)
    gravity = next(r for r in report["results"] if r["method"] == "gravity")["assessment"]
    assert plan["method"] == report["recommended"] == "gravity" and plan["recommended"]
    assert plan["spacing_m"] == gravity["station_spacing"] and plan["profile_length_m"] == gravity["profile_length"]
    notes = core.line_notes(60.0, plan, offset_m=40.0)
    assert "asks for at least" in notes[0] and "passes 40 m from the target" in notes[1]
    assert "a line to one side sees less" in notes[1]
    only_magnetic = core.evaluate(CAVITY, WHERE, ["magnetic"])                    # a cave in limestone: no contrast
    plan = core.layout(only_magnetic)
    assert only_magnetic["recommended"] is None and plan["method"] == "magnetic" and not plan["recommended"]
    assert "not expected to detect" in core.line_notes(500.0, plan)[-1]
    assert core.layout(core.evaluate(CAVITY, {}, ["magnetic"])) is None           # no location: nothing was assessed
