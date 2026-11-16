"""Resistivity is not part of the QGIS plugin. Stub written by qgis/build.py: the library's defaults, and
a method that says it is not available."""

DEFAULT_ARRAY = 'dipole-dipole'
DEFAULT_ELECTRODES = 48
DEFAULT_NOISE_PERCENT = 3.0


def available() -> bool:
    return False


def run(t, s):
    raise RuntimeError("resistivity (ERT) is not included in the QGIS plugin")


def remote(target, survey, url):
    raise RuntimeError("resistivity (ERT) is not included in the QGIS plugin")
