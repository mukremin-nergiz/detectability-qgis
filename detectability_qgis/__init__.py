"""Detectability for QGIS: will a survey see the target?"""


def classFactory(iface):  # noqa: N802  (the name QGIS calls)
    from .plugin import DetectabilityPlugin

    return DetectabilityPlugin(iface)
