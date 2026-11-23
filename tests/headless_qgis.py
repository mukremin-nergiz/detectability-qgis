"""The whole plugin in a QGIS without a screen: load, panel, target, line, stations, Processing, unload.

Run with the Python that belongs to a QGIS installation, from the folder above tests/:

    QT_QPA_PLATFORM=offscreen python3 tests/headless_qgis.py                 (Linux, a QGIS container)
    python-qgis-ltr.bat tests\\headless_qgis.py                               (Windows, OSGeo4W)

Prints one line of JSON and exits 0 only if every check holds. It stands in for the QGIS window with a small
object that offers what the plugin asks of it; the map canvas, the widgets and Processing are the real ones.
"""
import json
import os
import pathlib
import sys
import traceback

if sys.platform != "win32":        # a Windows runner has a desktop; elsewhere there is no screen to draw on
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))     # the folder that holds detectability_qgis/

from qgis.core import (Qgis, QgsApplication, QgsCoordinateReferenceSystem, QgsFeature, QgsGeometry, QgsPointXY,  # noqa: E402
                       QgsProject, QgsVectorLayer)
from qgis.gui import QgsMapCanvas  # noqa: E402
from qgis.PyQt.QtCore import QT_VERSION_STR  # noqa: E402
from qgis.PyQt.QtWidgets import QMainWindow  # noqa: E402

app = QgsApplication([], True)
app.initQgis()


class Window:
    """What the plugin uses of the QGIS main window."""

    def __init__(self):
        self.main = QMainWindow()
        self.canvas = QgsMapCanvas(self.main)
        self.canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:3857"))
        self.docks, self.menu = [], []

    def mainWindow(self):  # noqa: N802
        return self.main

    def mapCanvas(self):  # noqa: N802
        return self.canvas

    def activeLayer(self):  # noqa: N802
        return None

    def addDockWidget(self, area, dock):  # noqa: N802
        self.main.addDockWidget(area, dock)
        self.docks.append(dock)

    def removeDockWidget(self, dock):  # noqa: N802
        self.main.removeDockWidget(dock)
        self.docks.remove(dock)

    def addPluginToMenu(self, name, action):  # noqa: N802
        self.menu.append(action)

    def removePluginMenu(self, name, action):  # noqa: N802
        self.menu.remove(action)


log = {"qgis": Qgis.QGIS_VERSION, "qt": QT_VERSION_STR, "python": sys.version.split()[0], "platform": sys.platform}
ok = False
try:
    import numpy

    log["numpy"] = numpy.__version__
    for folder in (os.path.join(QgsApplication.pkgDataPath(), "python", "plugins"),
                   os.path.join(QgsApplication.prefixPath(), "share", "qgis", "python", "plugins")):
        if os.path.isdir(folder) and folder not in sys.path:
            sys.path.append(folder)
    import processing
    from processing.core.Processing import Processing

    Processing.initialize()

    import detectability_qgis
    from detectability_qgis import core, geo

    window = Window()
    plugin = detectability_qgis.classFactory(window)
    plugin.initGui()
    plugin.toggle(True)
    panel = plugin.panel
    assert window.docks == [panel] and len(window.menu) == 1

    target = QgsPointXY(37.0200, 39.7500)
    panel.set_target(target)
    panel.set_line([QgsPointXY(37.0200 - 200 / 85500.0, 39.7500), QgsPointXY(37.0200 + 200 / 85500.0, 39.7500)])
    log["line_m"], log["azimuth"] = round(panel.line.length_m, 2), round(panel.line.azimuth, 1)
    assert 395 < panel.line.length_m < 405 and abs(panel.line.azimuth - 90) < 0.5 and panel.line.offset_m(target) < 0.5
    panel.time_choice.setCurrentIndex(3)
    assert abs(panel.magnetic_time.value() - 3.6) < 1e-9
    panel.run()
    text = panel.out.toPlainText()
    assert "Gravity: clearly detectable" in text and "114" in text and "added in quadrature: 4.12 nT" in text, text[:400]
    assert panel.add_stations.isEnabled()
    before = len(QgsProject.instance().mapLayers())
    panel.make_stations()
    made = [l for l in QgsProject.instance().mapLayers().values()][-1]
    feats = list(made.getFeatures())
    assert len(QgsProject.instance().mapLayers()) == before + 1 and len(feats) == 81, len(feats)
    span = geo.Line([feats[0].geometry().asPoint(), feats[-1].geometry().asPoint()]).length_m
    assert abs(span - 400.0) < 0.01 and feats[0]["method"] == "Gravity" and feats[0]["library"] == core.LIBRARY_VERSION
    log["stations"], log["span_m"] = len(feats), round(span, 3)

    # a line spacing: the worst case between two lines, and back to a line over the target
    assert panel.line_spacing.value() == 0 and panel.line_spacing.text() == "a line over the target"
    panel.line_spacing.setValue(60.0)
    panel.run()
    spaced = panel.out.toPlainText()
    assert "Worst case between lines 60 m apart" in spaced and "worst case for an ideal survey" in spaced, spaced[:600]
    assert "114" not in spaced.split("Station spacing")[0]
    panel.line_spacing.setValue(0.0)
    panel.run()
    assert panel.out.toPlainText() == text
    log["line_spacing"] = "ok"

    # remanence: a Koenigsberger ratio reaches the library and is reported; none gives the same result as before
    assert panel.koenigsberger.value() == 0 and panel.koenigsberger.text() == "none" and panel.remanence.text() == "none"
    panel.koenigsberger.setValue(4.1)
    panel.run()
    assert "Koenigsberger ratio given (Q = 4.1" in panel.out.toPlainText(), panel.out.toPlainText()[:800]
    panel.koenigsberger.setValue(0.0)
    panel.remanence.setValue(1.5)
    panel.remanence_inclination.setValue(60.0)
    panel.run()
    assert "remanent magnetisation given (1.5 A/m" in panel.out.toPlainText(), panel.out.toPlainText()[:800]
    panel.koenigsberger.setValue(2.0)
    panel.run()
    assert "not both" in panel.out.toPlainText(), panel.out.toPlainText()[:400]
    panel.koenigsberger.setValue(0.0)
    panel.remanence.setValue(0.0)
    panel.remanence_inclination.setValue(0.0)
    panel.run()
    assert panel.out.toPlainText() == text
    log["remanence"] = "ok"

    # the map tools, driven the way a click drives them
    panel.clear_map()
    panel.start_line()
    tool = window.canvas.mapTool()
    assert tool is not None
    to_map = panel._to_canvas
    panel._line_clicked(to_map(QgsPointXY(37.0190, 39.7495)))
    panel._line_clicked(to_map(QgsPointXY(37.0210, 39.7505)))
    assert panel.line is not None and 190 < panel.line.length_m < 220 and window.canvas.mapTool() is not tool
    panel.start_target()
    panel._target_clicked(to_map(QgsPointXY(37.0200, 39.7500)))
    assert abs(panel.latitude.value() - 39.75) < 1e-4 and abs(panel.longitude.value() - 37.02) < 1e-4

    # Processing, on two lines in UTM 37N
    lines = QgsVectorLayer("LineString?crs=EPSG:32637", "lines", "memory")
    add = []
    for wkt in ("LINESTRING(330000 4401000, 330300 4401000)", "LINESTRING(330000 4402000, 330000 4402120, 330080 4402120)"):
        f = QgsFeature()
        f.setGeometry(QgsGeometry.fromWkt(wkt))
        add.append(f)
    lines.dataProvider().addFeatures(add)
    ids = [a.id() for a in QgsApplication.processingRegistry().algorithms() if a.id().startswith("detectability:")]
    assert ids == ["detectability:stations"], ids
    out = processing.run("detectability:stations", {"INPUT": lines, "SHAPE": 0, "DEPTH_TOP": 15, "SIZE": 20,
                                                    "MATERIAL": core.MATERIALS.index("air"),
                                                    "HOST": core.MATERIALS.index("limestone"), "METHOD": 0,
                                                    "OUTPUT": "memory:"})["OUTPUT"]
    counts = {}
    for f in out.getFeatures():
        counts[f["line"]] = counts.get(f["line"], 0) + 1
    log["processing"] = sorted(counts.values())
    assert sorted(counts.values()) == [41, 61] and out.crs().authid() == "EPSG:4326"
    magnetic = processing.run("detectability:stations", {"INPUT": lines, "SHAPE": 4, "DEPTH_TOP": 2, "SIZE": 5,
                                                         "DEPTH_BOTTOM": 60, "MATERIAL": core.MATERIALS.index("basalt"),
                                                         "HOST": core.MATERIALS.index("sandstone"), "METHOD": 1,
                                                         "MAGNETIC_TIME_NOISE": 3.6, "DATE": "2027-03-01",
                                                         "OUTPUT": "memory:"})["OUTPUT"]
    first = next(magnetic.getFeatures())
    assert first["method"] == "Magnetic" and first["verdict"] == "clearly detectable"
    log["magnetic_stations"] = magnetic.featureCount()
    remanent = processing.run("detectability:stations", {"INPUT": lines, "SHAPE": 4, "DEPTH_TOP": 2, "SIZE": 5,
                                                         "DEPTH_BOTTOM": 60, "MATERIAL": core.MATERIALS.index("basalt"),
                                                         "HOST": core.MATERIALS.index("sandstone"), "METHOD": 1,
                                                         "MAGNETIC_TIME_NOISE": 3.6, "DATE": "2027-03-01",
                                                         "KOENIGSBERGER_RATIO": 2.0, "OUTPUT": "memory:"})["OUTPUT"]
    snr = next(magnetic.getFeatures())["signal_noise"], next(remanent.getFeatures())["signal_noise"]
    assert abs(snr[1] / snr[0] - 3.0) < 1e-6, snr          # along the present field: 1 + Q times the induced
    log["processing_remanence"] = round(snr[1] / snr[0], 6)

    plugin.unload()
    assert window.docks == [] and window.menu == []
    assert not [a for a in QgsApplication.processingRegistry().algorithms() if a.id().startswith("detectability:")]
    ok = True
except Exception:  # noqa: BLE001
    log["error"] = traceback.format_exc()
log["ok"] = ok
print("RESULT " + json.dumps(log))
sys.stdout.flush()
os._exit(0 if ok else 1)
