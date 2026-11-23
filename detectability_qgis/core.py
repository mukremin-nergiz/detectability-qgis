"""What the panel asks the library, with no Qt and no QGIS in it, so it can be tested on its own.

Python 3.9 is the oldest interpreter this has to run on (QGIS for Windows before spring 2024).
"""
from __future__ import annotations

import math

from .lib import detectability
from .lib.detectability import detect, rocks, survey as _survey

LIBRARY_VERSION = detectability.__version__
FEEDBACK_URL = "https://github.com/mukremin-nergiz/detectability/issues/new/choose"

#: Methods offered. Resistivity needs a finite-element package that QGIS does not ship; it is not offered.
METHODS = (("gravity", "Gravity"), ("magnetic", "Magnetic"), ("gradient", "Magnetic gradient"), ("gpr", "GPR"))
SHAPES = (("sphere", "Sphere"), ("horizontal_cylinder", "Tunnel / pipe"), ("vertical_cylinder", "Shaft / well"),
          ("prism", "Room / block"), ("dyke", "Wall / dyke"), ("contact", "Fault / contact"))
NEEDS_BOTTOM = _survey.NEEDS_BOTTOM
NEEDS_SIZE = _survey.NEEDS_SIZE
MATERIALS = tuple(rocks.DENSITY_G_CM3)

#: The same choices and figures as the website's form (web/templates/_noise.html, web/app.py).
GRAVITY_SITE_UGAL = (("Quiet", 3.0), ("Typical", 10.0), ("Urban", 25.0))
MAGNETIC_TIME_NT = (("Included in site noise", 0.0), ("Base readings", 0.4), ("No correction", 3.6))
DEFAULT_GRAVITY_FIELD_UGAL = detect.DEFAULT_FIELD_NOISE_UGAL
DEFAULT_MAGNETIC_SITE_NT = detect.DEFAULT_FIELD_NOISE_NT


def with_line_spacing(survey: dict, spacing_m) -> dict:
    """The survey with the spacing of its parallel lines, when one is given. Zero or nothing leaves it as it is: the
    result is then for a line over the target, as before. With a spacing the library assesses a compact target where
    the survey reads least between two lines (gravity, magnetic and magnetic gradient)."""
    survey = dict(survey)
    if spacing_m:
        survey["line_spacing"] = float(spacing_m)
    return survey


def with_remanence(target: dict, remanence=0.0, inclination=0.0, declination=0.0, koenigsberger_ratio=0.0) -> dict:
    """The target with a remanent magnetisation, added by the library to the induced one (magnetic and gradient).

    Either as a vector, ``remanence`` (A/m) with its inclination (degrees, down positive) and declination (degrees east
    of north), or as a Koenigsberger ratio Q, remanent over induced, taken along the present field. Zero (or nothing)
    for both leaves the target as it is: induced magnetisation only, as before. Giving both is refused by the library,
    with its own message."""
    target = dict(target)
    if remanence:
        target.update(remanence=float(remanence), remanence_inclination=float(inclination),
                      remanence_declination=float(declination))
    if koenigsberger_ratio:
        target["koenigsberger_ratio"] = float(koenigsberger_ratio)
    return target


def evaluate(target: dict, survey: dict, methods, magnetic_time_noise: float = 0.0) -> dict:
    """Run the library and return its report as plain data.

    ``magnetic_time_noise`` (nT) is the time variation of the field, as a part of the magnetic noise: it is added in
    quadrature to the site noise, never put in its place. Zero leaves the survey as given.
    """
    survey = dict(survey)
    parts = None
    if magnetic_time_noise:
        if not 0 <= magnetic_time_noise <= 1000:
            raise ValueError("magnetic time variation: between 0 and 1000 nT")
        site = float(survey.get("magnetic_field_noise", DEFAULT_MAGNETIC_SITE_NT))
        survey["magnetic_field_noise"] = math.hypot(site, magnetic_time_noise)
        parts = {"site": site, "time": float(magnetic_time_noise), "field": survey["magnetic_field_noise"]}
    report = detectability.evaluate(target, survey, methods=list(methods)).to_dict(profile=False)
    if parts:
        for r in report["results"]:
            if r["method"] == "magnetic":
                r["field_noise_parts"] = parts
    return report


def _figure(v: float) -> str:
    return f"{v:,.0f}" if abs(v) >= 100 else f"{v:.3g}"


def rows(report: dict) -> list:
    """One row a method for the result table: name, verdict, signal-to-noise, peak, noise, spacing, profile."""
    names = dict(METHODS)
    out = []
    for r in report["results"]:
        a = r.get("assessment")
        if not r["available"] or not a:
            out.append({"method": names.get(r["method"], r["method"]), "verdict": "not assessed",
                        "note": r.get("reason", ""), "available": False})
            continue
        out.append({"method": names.get(r["method"], r["method"]), "available": True, "verdict": a["verdict"],
                    "snr": _figure(a["snr"]), "peak": f"{_figure(a['peak'])} {a['units']}",
                    "noise": f"{_figure(a['noise'])} {a['units']}", "spacing": f"{_figure(a['station_spacing'])} m",
                    "profile": f"{_figure(a['profile_length'])} m", "assumptions": list(a["assumptions"]),
                    "parts": r.get("field_noise_parts"), "lines": _between_lines(a)})
    return out


def _between_lines(a: dict):
    """One sentence when the figures are the worst case between two survey lines, else None."""
    if a.get("line_spacing") is None:
        return None
    return (f"Worst case between lines {_figure(a['line_spacing'])} m apart: {100 * a['peak'] / a['peak_best_line']:.0f} % "
            f"of the best line ({_figure(a['peak_best_line'])} {a['units']}); a line over the target reads "
            f"{_figure(a['peak_over_target'])} {a['units']}.")


def layout(report: dict):
    """Which method the stations are laid out for, and at what spacing.

    The recommended method if there is one; otherwise the assessed method with the best signal-to-noise, so that a
    line can still be planned for a target the model calls not detectable (the layer then says so). None when no
    method was assessed at all.
    """
    assessed = [r for r in report["results"] if r["available"] and r.get("assessment")]
    if not assessed:
        return None
    chosen = next((r for r in assessed if r["method"] == report.get("recommended")), None)
    if chosen is None:
        chosen = max(assessed, key=lambda r: r["assessment"]["snr"])
    a = chosen["assessment"]
    return {"method": chosen["method"], "name": dict(METHODS).get(chosen["method"], chosen["method"]),
            "verdict": a["verdict"], "snr": float(a["snr"]), "spacing_m": float(a["station_spacing"]),
            "profile_length_m": float(a["profile_length"]), "recommended": chosen["method"] == report.get("recommended"),
            "line_spacing_m": a.get("line_spacing")}


def station_distances(length_m: float, spacing_m: float, limit: int = 20000) -> list:
    """Distances of the stations along a line, from its start: every ``spacing_m``, the first at 0.

    The last station is the last whole step that still lies on the line; the line's end gets a station only if it
    falls on a step. More than ``limit`` stations is refused: that is a wrong unit or a wrong line, not a survey.
    """
    if not (length_m > 0 and spacing_m > 0):
        raise ValueError("the line and the station spacing must both be longer than zero")
    count = int(math.floor(length_m / spacing_m + 1e-9)) + 1
    if count > limit:
        raise ValueError(f"{count:,} stations: check the line and the spacing")
    return [round(i * spacing_m, 6) for i in range(count)]


def line_notes(length_m: float, plan: dict, offset_m=None) -> list:
    """What to tell the user about the line, in plain sentences: length against the model's minimum, and how far
    the line passes from the target. The model's profile runs across the middle of the target."""
    notes = []
    need = plan["profile_length_m"]
    if length_m + 1e-6 < need:
        notes.append(f"The line is {_figure(length_m)} m long; the model asks for at least {_figure(need)} m, so that "
                     "the anomaly can be told from the background on both sides.")
    else:
        notes.append(f"The line is {_figure(length_m)} m long (the model asks for at least {_figure(need)} m).")
    if offset_m is not None:
        if plan.get("line_spacing_m") is not None:
            notes.append(f"The line passes {_figure(offset_m)} m from the target point. The figures above are the worst "
                         f"case between lines {_figure(plan['line_spacing_m'])} m apart, not those of this one line.")
        elif offset_m > max(plan["spacing_m"], 1.0):
            notes.append(f"The line passes {_figure(offset_m)} m from the target point. The model's profile runs across "
                         "the middle of the target: a line to one side sees less than the figures above.")
        else:
            notes.append(f"The line passes {_figure(offset_m)} m from the target point.")
    if plan["verdict"] == "not detectable":
        notes.append(f"{plan['name']} is not expected to detect this target; the stations are laid out at the spacing "
                     "the model gives all the same.")
    return notes
