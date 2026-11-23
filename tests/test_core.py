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


def test_a_line_spacing_gives_the_worst_case_between_two_lines_and_zero_changes_nothing():
    body = {**CAVITY, "depth_top": 10.0}                       # centre 20 m down
    plain = core.evaluate(body, {}, ["gravity"])
    assert core.with_line_spacing({"date": "2027-03-01"}, 0.0) == {"date": "2027-03-01"}
    assert core.evaluate(body, core.with_line_spacing({}, 0.0), ["gravity"])["results"] == plain["results"]
    assert core.rows(plain)[0]["lines"] is None and core.layout(plain)["line_spacing_m"] is None
    spaced = core.evaluate(body, core.with_line_spacing({}, 40.0), ["gravity"])
    a, b = plain["results"][0]["assessment"], spaced["results"][0]["assessment"]
    assert abs(b["peak"] / a["peak"] - 2 ** -1.5) < 1e-6        # a sphere 20 m down, seen from a line 20 m aside
    row = core.rows(spaced)[0]
    assert row["lines"].startswith("Worst case between lines 40 m apart: 35 % of the best line (178 µGal)")
    assert any("worst case for an ideal survey" in line for line in row["assumptions"])
    plan = core.layout(spaced)
    assert plan["line_spacing_m"] == 40.0
    assert "worst case between lines 40 m apart, not those of this one line" in core.line_notes(400.0, plan, 12.0)[1]
    tunnel = {"shape": "horizontal_cylinder", "depth_top": 4.0, "size": 3.0, "material": "air", "host": "limestone"}
    assert core.rows(core.evaluate(tunnel, core.with_line_spacing({}, 40.0), ["gravity"]))[0]["lines"] is None


def test_remanence_is_passed_to_the_library_and_zero_changes_nothing():
    body = {"shape": "sphere", "depth_top": 15.0, "size": 20.0, "material": "basalt", "host": "limestone"}
    plain = core.evaluate(body, WHERE, ["magnetic"])
    assert core.with_remanence(body) == body and core.with_remanence(body, 0.0, 30.0, 10.0, 0.0) == body
    assert core.evaluate(core.with_remanence(body), WHERE, ["magnetic"])["results"] == plain["results"]
    a = plain["results"][0]["assessment"]
    assert any("induced magnetisation only" in line for line in a["assumptions"])
    # a Koenigsberger ratio along the present field: the response of this linear model grows by 1 + Q
    q = core.evaluate(core.with_remanence(body, koenigsberger_ratio=2.0), WHERE, ["magnetic"])["results"][0]["assessment"]
    assert abs(q["peak"] / a["peak"] - 3.0) < 1e-6
    assert any("Koenigsberger ratio given (Q = 2" in line for line in q["assumptions"])
    # a vector: all three are passed, and the result says so
    v = core.with_remanence(body, 1.5, 60.0, 10.0)
    assert (v["remanence"], v["remanence_inclination"], v["remanence_declination"]) == (1.5, 60.0, 10.0)
    va = core.evaluate(v, WHERE, ["magnetic"])["results"][0]["assessment"]
    assert va["peak"] != a["peak"] and any("remanent magnetisation given (1.5 A/m" in line for line in va["assumptions"])
    # both at once: refused by the library with its own message
    try:
        core.evaluate(core.with_remanence(body, 1.5, 60.0, 10.0, 2.0), WHERE, ["magnetic"])
    except ValueError as error:
        assert "not both" in str(error)
    else:
        raise AssertionError("both a vector and a ratio were accepted")


def test_own_contrasts_replace_the_material_tables_and_zero_takes_the_tables():
    plain = core.evaluate(CAVITY, {}, ["gravity"])
    assert core.with_contrasts(CAVITY) == CAVITY and core.with_contrasts(CAVITY, 0.0, 0.0) == CAVITY
    assert core.evaluate(core.with_contrasts(CAVITY), {}, ["gravity"])["results"] == plain["results"]
    table = core.rocks.contrast("air", "limestone")
    half = core.evaluate(core.with_contrasts(CAVITY, density_contrast=table / 2), {}, ["gravity"])
    assert abs(half["results"][0]["assessment"]["peak"] / plain["results"][0]["assessment"]["peak"] - 0.5) < 1e-9
    body = {"shape": "sphere", "depth_top": 15.0, "size": 20.0, "material": "basalt", "host": "limestone"}
    m = core.evaluate(body, WHERE, ["magnetic"])["results"][0]["assessment"]["peak"]
    k = core.rocks.susceptibility_contrast("basalt", "limestone")
    m2 = core.evaluate(core.with_contrasts(body, susceptibility_contrast=2 * k), WHERE, ["magnetic"])
    assert abs(m2["results"][0]["assessment"]["peak"] / m - 2.0) < 1e-6
    # the contrast and a Koenigsberger ratio together: the ratio applies to the given susceptibility
    both = core.with_remanence(core.with_contrasts(body, susceptibility_contrast=2 * k), koenigsberger_ratio=1.0)
    assert abs(core.evaluate(both, WHERE, ["magnetic"])["results"][0]["assessment"]["peak"] / m - 4.0) < 1e-6
