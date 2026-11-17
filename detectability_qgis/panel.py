"""The dock panel: describe the target and the survey, read the verdict for each method.

Written for Qt5 (QGIS 3) and Qt6 (QGIS 4) alike: imports come from qgis.PyQt and enums are fully qualified.
"""
from __future__ import annotations

import html

from qgis.core import Qgis, QgsPointXY, QgsProject
from qgis.gui import QgsMapToolEmitPoint, QgsRubberBand, QgsVertexMarker
from qgis.PyQt.QtCore import QDate, Qt
from qgis.PyQt.QtWidgets import (QCheckBox, QComboBox, QDateEdit, QDockWidget, QDoubleSpinBox, QFormLayout, QGroupBox,
                                 QHBoxLayout, QLabel, QPushButton, QScrollArea, QTextBrowser, QVBoxLayout, QWidget)

from . import core, geo

VERDICT_COLOUR = {"clearly detectable": "#1b7a43", "marginal": "#9a6700", "not detectable": "#b42318"}


def _spin(value: float, low: float, high: float, decimals: int = 2, suffix: str = "") -> QDoubleSpinBox:
    box = QDoubleSpinBox()
    box.setDecimals(decimals)
    box.setRange(low, high)
    box.setValue(value)
    if suffix:
        box.setSuffix(" " + suffix)
    return box


class DetectabilityPanel(QDockWidget):
    def __init__(self, iface, parent=None):
        super().__init__("Detectability", parent or iface.mainWindow())
        self.iface = iface
        self.setObjectName("DetectabilityPanel")
        body = QWidget()
        outer = QVBoxLayout(body)

        # Target
        target = QGroupBox("Target")
        form = QFormLayout(target)
        self.shape = QComboBox()
        for key, label in core.SHAPES:
            self.shape.addItem(label, key)
        self.depth_top = _spin(15.0, 0.01, 100000.0, suffix="m")
        self.size = _spin(20.0, 0.01, 100000.0, suffix="m")
        self.depth_bottom = _spin(25.0, 0.02, 100000.0, suffix="m")
        self.length = _spin(20.0, 0.01, 100000.0, suffix="m")
        self.material, self.host = QComboBox(), QComboBox()
        for box, chosen in ((self.material, "air"), (self.host, "limestone")):
            box.addItems([m for m in core.MATERIALS])
            box.setCurrentIndex(max(box.findText(chosen), 0))
        form.addRow("Shape", self.shape)
        form.addRow("Depth to top", self.depth_top)
        form.addRow("Size (diameter or width)", self.size)
        form.addRow("Depth to bottom", self.depth_bottom)
        form.addRow("Length across the profile", self.length)
        form.addRow("Target material", self.material)
        form.addRow("Host material", self.host)
        outer.addWidget(target)

        # Methods
        methods = QGroupBox("Methods")
        row = QHBoxLayout(methods)
        self.methods = {}
        for key, label in core.METHODS:
            box = QCheckBox(label)
            box.setChecked(key in ("gravity", "magnetic"))
            self.methods[key] = box
            row.addWidget(box)
        outer.addWidget(methods)

        # Survey
        survey = QGroupBox("Survey")
        form = QFormLayout(survey)
        self.gravity_noise = _spin(core.DEFAULT_GRAVITY_FIELD_UGAL, 0.0, 100000.0, 1, "µGal")
        self.gravity_site = QComboBox()
        self.gravity_site.addItem("Custom", None)
        for name, value in core.GRAVITY_SITE_UGAL:
            self.gravity_site.addItem(f"{name} {value:g}", value)
        self.magnetic_site = _spin(core.DEFAULT_MAGNETIC_SITE_NT, 0.0, 100000.0, 2, "nT")
        self.magnetic_time = _spin(0.0, 0.0, 1000.0, 2, "nT")
        self.time_choice = QComboBox()
        self.time_choice.addItem("Custom", None)
        for name, value in core.MAGNETIC_TIME_NT:
            self.time_choice.addItem(f"{name} ({value:g})" if value == 0 else f"{name} {value:g}", value)
        self.latitude = _spin(0.0, -90.0, 90.0, 5, "°")
        self.longitude = _spin(0.0, -180.0, 180.0, 5, "°")
        self.date = QDateEdit(QDate.currentDate())
        self.date.setDisplayFormat("yyyy-MM-dd")
        self.date.setCalendarPopup(True)
        from_map = QPushButton("Use the centre of the map")
        from_map.clicked.connect(self.use_map_centre)
        form.addRow("Gravity field noise", self.gravity_noise)
        form.addRow("Site", self.gravity_site)
        form.addRow("Magnetic site noise", self.magnetic_site)
        form.addRow("Magnetic time variation", self.magnetic_time)
        form.addRow("Time variation", self.time_choice)
        form.addRow("Latitude", self.latitude)
        form.addRow("Longitude", self.longitude)
        form.addRow("", from_map)
        form.addRow("Survey date", self.date)
        outer.addWidget(survey)

        # Map: where the target is, and the line the survey will follow
        on_map = QGroupBox("On the map")
        col = QVBoxLayout(on_map)
        row = QHBoxLayout()
        self.pick_target = QPushButton("Pick the target")
        self.draw_line = QPushButton("Draw a line")
        self.take_line = QPushButton("Use the selected line")
        clear = QPushButton("Clear")
        for b in (self.pick_target, self.draw_line, self.take_line, clear):
            row.addWidget(b)
        col.addLayout(row)
        self.map_note = QLabel("Click the target on the map to take its latitude and longitude. Draw the survey line "
                               "with two clicks, or select a line feature and take it: the stations are laid along it.")
        self.map_note.setWordWrap(True)
        col.addWidget(self.map_note)
        outer.addWidget(on_map)
        self.pick_target.clicked.connect(self.start_target)
        self.draw_line.clicked.connect(self.start_line)
        self.take_line.clicked.connect(self.use_selected_line)
        clear.clicked.connect(self.clear_map)
        self.target_point = None        # WGS84
        self.line = None                # geo.Line
        self.report = None
        self._tool = self._previous_tool = self._band = self._marker = None
        self._clicks = []

        run = QPushButton("Will the survey see it?")
        run.clicked.connect(self.run)
        outer.addWidget(run)
        self.add_stations = QPushButton("Add the stations to the map")
        self.add_stations.setEnabled(False)
        self.add_stations.clicked.connect(self.make_stations)
        outer.addWidget(self.add_stations)
        self.out = QTextBrowser()
        self.out.setOpenExternalLinks(False)
        self.out.setMinimumHeight(220)
        outer.addWidget(self.out, 1)
        note = QLabel(f"Detectability {core.LIBRARY_VERSION}. Model-based expectations under the stated assumptions, "
                      "not guarantees. No network connection, no data collected.")
        note.setWordWrap(True)
        outer.addWidget(note)
        feedback = QLabel(f'Used this on a real survey? <a href="{core.FEEDBACK_URL}">Tell me how it compared</a>.')
        feedback.setWordWrap(True)
        feedback.setOpenExternalLinks(True)  # opens the user's browser; the plugin itself makes no connection
        outer.addWidget(feedback)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        self.setWidget(scroll)

        self.shape.currentIndexChanged.connect(self.sync)
        self.gravity_site.currentIndexChanged.connect(lambda _: self._preset(self.gravity_site, self.gravity_noise))
        self.time_choice.currentIndexChanged.connect(lambda _: self._preset(self.time_choice, self.magnetic_time))
        self.gravity_noise.valueChanged.connect(lambda v: self._mark(self.gravity_site, v))
        self.magnetic_time.valueChanged.connect(lambda v: self._mark(self.time_choice, v))
        self._mark(self.gravity_site, self.gravity_noise.value())
        self._mark(self.time_choice, self.magnetic_time.value())
        self.sync()
        self.use_map_centre()

    # A preset sets the figure; any other figure typed in shows as "Custom".
    def _preset(self, choice: QComboBox, box: QDoubleSpinBox) -> None:
        value = choice.currentData()
        if value is not None and abs(box.value() - value) > 1e-9:
            box.setValue(value)

    def _mark(self, choice: QComboBox, value: float) -> None:
        index = next((i for i in range(1, choice.count()) if abs(choice.itemData(i) - value) < 1e-9), 0)
        if choice.currentIndex() != index:
            choice.blockSignals(True)
            choice.setCurrentIndex(index)
            choice.blockSignals(False)

    def sync(self) -> None:
        shape = self.shape.currentData()
        self.size.setEnabled(shape in core.NEEDS_SIZE)
        self.depth_bottom.setEnabled(shape in core.NEEDS_BOTTOM)
        self.length.setEnabled(shape == "prism")

    def use_map_centre(self) -> None:
        """Latitude and longitude of the middle of the map view, for the main field of the magnetic methods."""
        try:
            canvas = self.iface.mapCanvas()
            self._set_location(geo.to_wgs84(canvas.center(), canvas.mapSettings().destinationCrs()))
        except Exception as error:  # noqa: BLE001  (a map without a usable projection must not break the panel)
            self.out.setPlainText(f"The map centre could not be read: {error}")

    def _set_location(self, point) -> bool:
        if -90 <= point.y() <= 90 and -180 <= point.x() <= 180:
            self.latitude.setValue(point.y())
            self.longitude.setValue(point.x())
            return True
        return False

    # --- map tools ---------------------------------------------------------------------------------------------

    def _canvas_crs(self):
        return self.iface.mapCanvas().mapSettings().destinationCrs()

    def _start_tool(self, on_click) -> None:
        canvas = self.iface.mapCanvas()
        self._end_tool()
        self._previous_tool = canvas.mapTool()
        self._tool = QgsMapToolEmitPoint(canvas)
        self._tool.canvasClicked.connect(on_click)
        canvas.setMapTool(self._tool)

    def _end_tool(self) -> None:
        canvas = self.iface.mapCanvas()
        if self._tool is not None:
            if canvas.mapTool() is self._tool:
                canvas.unsetMapTool(self._tool)
                if self._previous_tool is not None:
                    canvas.setMapTool(self._previous_tool)
            self._tool = self._previous_tool = None
        self._clicks = []

    def start_target(self) -> None:
        self.map_note.setText("Click the target on the map.")
        self._start_tool(self._target_clicked)

    def _target_clicked(self, point, _button=None) -> None:
        self.set_target(geo.to_wgs84(point, self._canvas_crs()))
        self._end_tool()

    def set_target(self, point_wgs84) -> None:
        """The target's place: its latitude and longitude go to the survey, and a cross marks it on the map."""
        if not self._set_location(point_wgs84):
            self.map_note.setText("That point is not on the Earth: check the project's projection.")
            return
        self.target_point = QgsPointXY(point_wgs84)
        self._draw()
        self._describe()

    def start_line(self) -> None:
        self.map_note.setText("Click the start of the survey line, then its end.")
        self._start_tool(self._line_clicked)

    def _line_clicked(self, point, _button=None) -> None:
        self._clicks.append(geo.to_wgs84(point, self._canvas_crs()))
        if len(self._clicks) == 2:
            clicks = list(self._clicks)
            self._end_tool()
            self.set_line(clicks)
        else:
            self.map_note.setText("Now click the end of the line.")

    def use_selected_line(self) -> None:
        layer = self.iface.activeLayer()
        chosen = layer.selectedFeatures() if layer is not None and hasattr(layer, "selectedFeatures") else []
        if len(chosen) != 1:
            self.map_note.setText("Select exactly one line feature in the active layer, then press the button again.")
            return
        try:
            self.set_line(geo.line_from_geometry(chosen[0].geometry(), layer.crs()).vertices)
        except ValueError as error:
            self.map_note.setText(str(error).capitalize() + ".")

    def set_line(self, vertices_wgs84) -> None:
        try:
            self.line = geo.Line(vertices_wgs84)
        except ValueError as error:
            self.line = None
            self.map_note.setText(str(error).capitalize() + ".")
            return
        if self.target_point is None:          # no target picked: the field is taken at the middle of the line
            self._set_location(self.line.midpoint)
        self.add_stations.setEnabled(False)    # the result on screen was computed before this line
        self._draw()
        self._describe()

    def clear_map(self) -> None:
        self._end_tool()
        self.target_point = self.line = None
        self.add_stations.setEnabled(False)
        self._draw()
        self.map_note.setText("Cleared. Pick the target, or draw or take a line.")

    def _draw(self) -> None:
        canvas = self.iface.mapCanvas()
        for item in (self._band, self._marker):
            if item is not None:
                canvas.scene().removeItem(item)
        self._band = self._marker = None
        if self.line is not None:
            self._band = QgsRubberBand(canvas, Qgis.GeometryType.Line)
            self._band.setWidth(2)
            self._band.setToGeometry(self.line.geometry(), geo.wgs84())
        if self.target_point is not None:
            self._marker = QgsVertexMarker(canvas)
            self._marker.setCenter(self._to_canvas(self.target_point))
            self._marker.setIconSize(14)
            self._marker.setPenWidth(2)

    def _to_canvas(self, point_wgs84):
        from qgis.core import QgsCoordinateTransform
        crs = self._canvas_crs()
        if not crs.isValid() or crs == geo.wgs84():
            return QgsPointXY(point_wgs84)
        return QgsCoordinateTransform(geo.wgs84(), crs, QgsProject.instance()).transform(point_wgs84)

    def _describe(self) -> None:
        parts = []
        if self.target_point is not None:
            parts.append(f"Target at {self.target_point.y():.5f}°, {self.target_point.x():.5f}°.")
        if self.line is not None:
            parts.append(f"Line {self.line.length_m:,.0f} m long, heading {self.line.azimuth:.0f}° east of north; the "
                         "profile direction of the magnetic methods follows it.")
            if self.target_point is not None:
                parts.append(f"It passes {self.line.offset_m(self.target_point):,.1f} m from the target.")
        self.map_note.setText(" ".join(parts))

    def make_stations(self) -> None:
        """A point layer with one station every recommended spacing along the line, for the result on screen."""
        if self.line is None or self.report is None:
            return
        plan = core.layout(self.report)
        if plan is None:
            return
        try:
            distances = core.station_distances(self.line.length_m, plan["spacing_m"])
        except ValueError as error:
            self.map_note.setText(str(error).capitalize() + ".")
            return
        layer = geo.station_layer(self.line, distances, plan, core.LIBRARY_VERSION,
                                  f"Detectability stations ({plan['name']}, every {plan['spacing_m']:g} m)")
        QgsProject.instance().addMapLayer(layer)
        self.map_note.setText(f"{len(distances)} stations added as a temporary layer; save it to keep it.")

    def close_map(self) -> None:
        """Take the plugin's marks and tool off the map (when the plugin is unloaded)."""
        self._end_tool()
        self.target_point = self.line = None
        self._draw()

    def inputs(self):
        shape = self.shape.currentData()
        target = {"shape": shape, "depth_top": self.depth_top.value(), "material": self.material.currentText(),
                  "host": self.host.currentText()}
        if shape in core.NEEDS_SIZE:
            target["size"] = self.size.value()
        if shape in core.NEEDS_BOTTOM:
            target["depth_bottom"] = self.depth_bottom.value()
        if shape == "prism":
            target["length"] = self.length.value()
        survey = {"gravity_field_noise": self.gravity_noise.value(), "magnetic_field_noise": self.magnetic_site.value(),
                  "latitude": self.latitude.value(), "longitude": self.longitude.value(),
                  "date": self.date.date().toString("yyyy-MM-dd")}
        if self.line is not None:
            survey["profile_azimuth"] = round(self.line.azimuth, 1)
        methods = [key for key, box in self.methods.items() if box.isChecked()]
        return target, survey, methods

    def run(self) -> None:
        target, survey, methods = self.inputs()
        if not methods:
            self.out.setPlainText("Tick at least one method.")
            return
        try:
            report = core.evaluate(target, survey, methods, self.magnetic_time.value())
        except Exception as error:  # noqa: BLE001  (the library's own message says what is wrong with the input)
            self.out.setPlainText(str(error))
            return
        self.report = report
        self.add_stations.setEnabled(self.line is not None and core.layout(report) is not None)
        self.out.setHtml(self.render(report))

    def render(self, report: dict) -> str:
        e = html.escape
        parts = []
        if report.get("recommended"):
            name = dict(core.METHODS).get(report["recommended"], report["recommended"])
            parts.append(f"<p><b>Recommended method:</b> {e(name)}</p>")
        for r in core.rows(report):
            if not r["available"]:
                parts.append(f"<p><b>{e(r['method'])}</b>: not assessed. {e(r['note'])}</p>")
                continue
            colour = VERDICT_COLOUR.get(r["verdict"], "#444444")
            parts.append(
                f"<p><b>{e(r['method'])}</b>: <span style='color:{colour}'><b>{e(r['verdict'])}</b></span><br>"
                f"Signal / noise {e(r['snr'])} &nbsp;·&nbsp; peak {e(r['peak'])} &nbsp;·&nbsp; noise {e(r['noise'])}<br>"
                f"Station spacing ≤ {e(r['spacing'])} &nbsp;·&nbsp; profile length ≥ {e(r['profile'])}</p>")
            if r.get("parts"):
                p = r["parts"]
                parts.append(f"<p>Field noise is site {p['site']:g} nT and time variation {p['time']:g} nT, added in "
                             f"quadrature: {p['field']:.3g} nT.</p>")
            if r["assumptions"]:
                parts.append("<ul>" + "".join(f"<li>{e(a)}</li>" for a in r["assumptions"]) + "</ul>")
        plan = core.layout(report)
        if self.line is not None and plan is not None:
            offset = self.line.offset_m(self.target_point) if self.target_point is not None else None
            notes = core.line_notes(self.line.length_m, plan, offset)
            count = len(core.station_distances(self.line.length_m, plan["spacing_m"]))
            parts.append(f"<p><b>Survey line</b> ({e(plan['name'])}, a station every {plan['spacing_m']:g} m: "
                         f"{count} stations)</p><ul>" + "".join(f"<li>{e(n)}</li>" for n in notes) + "</ul>")
        parts.append(f"<p style='color:#666666'>Detectability {e(report['version'])}. Model-based expectations under "
                     "the stated assumptions, not guarantees.</p>")
        return "".join(parts)
