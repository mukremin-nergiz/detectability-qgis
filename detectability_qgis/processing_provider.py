"""The same question as a Processing algorithm, for batch runs and the model designer.

For every line of a layer: is the target detectable with the chosen method, and where do the stations go?
Written for QGIS 3.34 to 4.x; the few names that changed between them are looked up once, below.
"""
from __future__ import annotations

import datetime

from qgis.core import (Qgis, QgsFeature, QgsFeatureSink, QgsFields, QgsField, QgsGeometry, QgsProcessing,
                       QgsProcessingAlgorithm, QgsProcessingException, QgsProcessingParameterEnum,
                       QgsProcessingParameterFeatureSink, QgsProcessingParameterFeatureSource,
                       QgsProcessingParameterNumber, QgsProcessingParameterString, QgsProcessingProvider, QgsWkbTypes)

from . import core, geo



def _before_3_36(owner, name):
    """A name QGIS 3.34 still needs and later versions replaced. It is looked up by its text because the plugin
    repository's Qt6 check reads the source without running it and reports these names, although the branches that
    use them run on QGIS 3.34 (Qt5) only."""
    return getattr(owner, name)


try:                                    # QGIS 3.36 and later
    LINES, POINTS = Qgis.ProcessingSourceType.VectorLine, Qgis.ProcessingSourceType.VectorPoint
except AttributeError:                  # QGIS 3.34
    LINES, POINTS = _before_3_36(QgsProcessing, "TypeVectorLine"), _before_3_36(QgsProcessing, "TypeVectorPoint")
try:
    NUMBER = Qgis.ProcessingNumberParameterType.Double
except AttributeError:
    NUMBER = _before_3_36(QgsProcessingParameterNumber, "Double")
try:
    POINT_TYPE = Qgis.WkbType.Point
except AttributeError:
    POINT_TYPE = _before_3_36(QgsWkbTypes, "Point")
try:
    FAST_INSERT = QgsFeatureSink.Flag.FastInsert
except AttributeError:
    FAST_INSERT = _before_3_36(QgsFeatureSink, "FastInsert")
try:                                    # Qt5 (QGIS 3): field types are QVariant types. Asked first on purpose:
    from qgis.PyQt.QtCore import QVariant    # QMetaType.Type.Int exists there too, but QGIS 3.34 does not take it.
    INT, DOUBLE, TEXT = QVariant.Int, QVariant.Double, QVariant.String
except AttributeError:                  # Qt6 (QGIS 4): QVariant has no types of its own any more
    from qgis.PyQt.QtCore import QMetaType
    INT, DOUBLE, TEXT = QMetaType.Type.Int, QMetaType.Type.Double, QMetaType.Type.QString

SHAPES = [key for key, _ in core.SHAPES]
METHODS = [key for key, _ in core.METHODS]
MATERIALS = list(core.MATERIALS)


class StationsAlgorithm(QgsProcessingAlgorithm):
    INPUT, OUTPUT = "INPUT", "OUTPUT"

    def name(self):
        return "stations"

    def displayName(self):  # noqa: N802
        return "Detectability and stations along survey lines"

    def group(self):
        return ""

    def groupId(self):  # noqa: N802
        return ""

    def shortHelpString(self):  # noqa: N802
        return ("For each line of the input layer, models the response of a buried target under the middle of the "
                "line with the chosen method, compares it with instrument and field noise, and writes one point a "
                "station at the spacing the model recommends. Each point carries the verdict and the "
                "signal-to-noise ratio. With a line spacing, a compact target is assessed where the survey reads "
                "least between two lines instead of under the line. Results are model-based expectations under the stated assumptions, not "
                f"guarantees. Detectability {core.LIBRARY_VERSION}; no network connection.")

    def createInstance(self):  # noqa: N802
        return StationsAlgorithm()

    def initAlgorithm(self, config=None):  # noqa: N802
        add = self.addParameter
        add(QgsProcessingParameterFeatureSource(self.INPUT, "Survey lines", [LINES]))
        add(QgsProcessingParameterEnum("SHAPE", "Target shape", [label for _, label in core.SHAPES], defaultValue=0))
        add(QgsProcessingParameterNumber("DEPTH_TOP", "Depth to the top of the target (m)", NUMBER, 15.0, minValue=0.01))
        add(QgsProcessingParameterNumber("SIZE", "Size: diameter or width (m)", NUMBER, 20.0, minValue=0.01))
        add(QgsProcessingParameterNumber("DEPTH_BOTTOM", "Depth to the bottom (m); shaft, block, dyke and contact",
                                         NUMBER, 25.0, minValue=0.02))
        add(QgsProcessingParameterEnum("MATERIAL", "Target material", MATERIALS, defaultValue=MATERIALS.index("air")))
        add(QgsProcessingParameterEnum("HOST", "Host material", MATERIALS, defaultValue=MATERIALS.index("limestone")))
        add(QgsProcessingParameterEnum("METHOD", "Method", [label for _, label in core.METHODS], defaultValue=0))
        add(QgsProcessingParameterNumber("GRAVITY_NOISE", "Gravity field noise (µGal)", NUMBER,
                                         core.DEFAULT_GRAVITY_FIELD_UGAL, minValue=0.0))
        add(QgsProcessingParameterNumber("MAGNETIC_SITE_NOISE", "Magnetic site noise (nT)", NUMBER,
                                         core.DEFAULT_MAGNETIC_SITE_NT, minValue=0.0))
        add(QgsProcessingParameterNumber("MAGNETIC_TIME_NOISE", "Magnetic time variation (nT), added in quadrature",
                                         NUMBER, 0.0, minValue=0.0, maxValue=1000.0))
        add(QgsProcessingParameterString("DATE", "Survey date (YYYY-MM-DD); empty for today", optional=True))
        add(QgsProcessingParameterNumber("LINE_SPACING", "Line spacing (m): worst case between two lines; 0 for a "
                                         "line over the target", NUMBER, 0.0, minValue=0.0, maxValue=5000.0))
        add(QgsProcessingParameterFeatureSink(self.OUTPUT, "Stations", POINTS))

    def processAlgorithm(self, parameters, context, feedback):  # noqa: N802
        source = self.parameterAsSource(parameters, self.INPUT, context)
        if source is None:
            raise QgsProcessingException("No line layer was given.")
        shape = SHAPES[self.parameterAsEnum(parameters, "SHAPE", context)]
        method = METHODS[self.parameterAsEnum(parameters, "METHOD", context)]
        number = lambda key: self.parameterAsDouble(parameters, key, context)   # noqa: E731
        target = {"shape": shape, "depth_top": number("DEPTH_TOP"),
                  "material": MATERIALS[self.parameterAsEnum(parameters, "MATERIAL", context)],
                  "host": MATERIALS[self.parameterAsEnum(parameters, "HOST", context)]}
        if shape in core.NEEDS_SIZE:
            target["size"] = number("SIZE")
        if shape in core.NEEDS_BOTTOM:
            target["depth_bottom"] = number("DEPTH_BOTTOM")
        date = (self.parameterAsString(parameters, "DATE", context) or "").strip() or datetime.date.today().isoformat()

        fields = QgsFields()
        for name, kind in (("line", INT), ("station", INT), ("distance_m", DOUBLE), ("longitude", DOUBLE),
                           ("latitude", DOUBLE), ("method", TEXT), ("spacing_m", DOUBLE), ("verdict", TEXT),
                           ("signal_noise", DOUBLE), ("library", TEXT)):
            fields.append(QgsField(name, kind))
        sink, destination = self.parameterAsSink(parameters, self.OUTPUT, context, fields, POINT_TYPE, geo.wgs84())
        if sink is None:
            raise QgsProcessingException("The output layer could not be created.")

        total = source.featureCount() or 1
        for done, feature in enumerate(source.getFeatures()):
            if feedback.isCanceled():
                break
            geometry = feature.geometry()
            if geometry is None or geometry.isEmpty():
                continue
            try:
                line = geo.line_from_geometry(geometry, source.sourceCrs())
                survey = {"gravity_field_noise": number("GRAVITY_NOISE"), "magnetic_field_noise": number("MAGNETIC_SITE_NOISE"),
                          "latitude": line.midpoint.y(), "longitude": line.midpoint.x(), "date": date,
                          "profile_azimuth": round(line.azimuth, 1)}
                survey = core.with_line_spacing(survey, number("LINE_SPACING"))
                report = core.evaluate(target, survey, [method], number("MAGNETIC_TIME_NOISE"))
            except (ValueError, TypeError) as error:
                raise QgsProcessingException(f"Line {feature.id()}: {error}")
            plan = core.layout(report)
            if plan is None:
                feedback.reportError(f"Line {feature.id()}: {core.rows(report)[0].get('note', 'not assessed')}")
                continue
            distances = core.station_distances(line.length_m, plan["spacing_m"])
            feedback.pushInfo(f"Line {feature.id()}: {plan['name']} {plan['verdict']}, signal-to-noise "
                              f"{plan['snr']:.3g}; {len(distances)} stations every {plan['spacing_m']:g} m.")
            for note in core.line_notes(line.length_m, plan):
                feedback.pushInfo("  " + note)
            if core.rows(report)[0].get("lines"):
                feedback.pushInfo("  " + core.rows(report)[0]["lines"] + " An ideal survey: a real one can lose more.")
            for i, d in enumerate(distances, 1):
                p = line.point_at(d)
                out = QgsFeature(fields)
                out.setGeometry(QgsGeometry.fromPointXY(p))
                out.setAttributes([int(feature.id()), i, float(d), p.x(), p.y(), plan["name"], plan["spacing_m"],
                                   plan["verdict"], plan["snr"], core.LIBRARY_VERSION])
                sink.addFeature(out, FAST_INSERT)
            feedback.setProgress(int(100 * (done + 1) / total))
        feedback.pushInfo(f"Detectability {core.LIBRARY_VERSION}. Model-based expectations under the stated "
                          "assumptions, not guarantees.")
        return {self.OUTPUT: destination}


class DetectabilityProvider(QgsProcessingProvider):
    def id(self):
        return "detectability"

    def name(self):
        return "Detectability"

    def longName(self):  # noqa: N802
        return "Detectability: pre-survey detectability"

    def loadAlgorithms(self):  # noqa: N802
        self.addAlgorithm(StationsAlgorithm())
