"""Lines, distances and station points on the map. Needs QGIS; no Qt widgets.

Distances are worked out in metres on a plane laid on the ground at the middle of the line (an azimuthal
equidistant projection centred there), whatever projection the map uses. Over a survey line, a few kilometres at
most, that plane and the ellipsoid agree to well under a millimetre per kilometre.
"""
from __future__ import annotations

import math

from qgis.core import (QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsFeature, QgsGeometry, QgsPointXY,
                       QgsProject, QgsVectorLayer)

WGS84 = "EPSG:4326"


def wgs84() -> QgsCoordinateReferenceSystem:
    return QgsCoordinateReferenceSystem(WGS84)


def to_wgs84(point: QgsPointXY, crs: QgsCoordinateReferenceSystem) -> QgsPointXY:
    """A map point as longitude (x) and latitude (y)."""
    target = wgs84()
    if not crs.isValid() or crs == target:
        return QgsPointXY(point)
    return QgsCoordinateTransform(crs, target, QgsProject.instance()).transform(point)


def _plane(lon: float, lat: float) -> QgsCoordinateReferenceSystem:
    return QgsCoordinateReferenceSystem.fromProj(
        f"+proj=aeqd +lat_0={lat:.8f} +lon_0={lon:.8f} +x_0=0 +y_0=0 +datum=WGS84 +units=m +no_defs")


class Line:
    """A survey line given by its vertices in WGS84 (longitude, latitude), measured in metres."""

    def __init__(self, vertices):
        self.vertices = [QgsPointXY(p) for p in vertices]
        if len(self.vertices) < 2:
            raise ValueError("a line needs two points")
        lon = sum(p.x() for p in self.vertices) / len(self.vertices)
        lat = sum(p.y() for p in self.vertices) / len(self.vertices)
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError("the line is not on the Earth: check the layer's projection")
        self._crs = _plane(lon, lat)
        self._to = QgsCoordinateTransform(wgs84(), self._crs, QgsProject.instance())
        self._back = QgsCoordinateTransform(self._crs, wgs84(), QgsProject.instance())
        self._xy = [self._to.transform(p) for p in self.vertices]
        self._steps = [math.hypot(b.x() - a.x(), b.y() - a.y()) for a, b in zip(self._xy, self._xy[1:])]
        self.length_m = float(sum(self._steps))
        if self.length_m <= 0:
            raise ValueError("the line has no length")
        self.midpoint = self.point_at(self.length_m / 2.0)

    @property
    def azimuth(self) -> float:
        """Direction from the first vertex to the last, in degrees east of north."""
        a, b = self._xy[0], self._xy[-1]
        return math.degrees(math.atan2(b.x() - a.x(), b.y() - a.y())) % 360.0

    def point_at(self, distance_m: float) -> QgsPointXY:
        """The point this far along the line from its start, in WGS84."""
        left = min(max(distance_m, 0.0), self.length_m)
        for (a, b), step in zip(zip(self._xy, self._xy[1:]), self._steps):
            if left <= step or (a, b) == (self._xy[-2], self._xy[-1]):
                f = 0.0 if step == 0 else min(left / step, 1.0)
                return self._back.transform(QgsPointXY(a.x() + f * (b.x() - a.x()), a.y() + f * (b.y() - a.y())))
            left -= step
        return QgsPointXY(self.vertices[-1])

    def offset_m(self, point_wgs84: QgsPointXY) -> float:
        """Shortest distance from a point to the line, in metres."""
        p = self._to.transform(QgsPointXY(point_wgs84))
        best = float("inf")
        for a, b in zip(self._xy, self._xy[1:]):
            dx, dy = b.x() - a.x(), b.y() - a.y()
            span = dx * dx + dy * dy
            f = 0.0 if span == 0 else min(max(((p.x() - a.x()) * dx + (p.y() - a.y()) * dy) / span, 0.0), 1.0)
            best = min(best, math.hypot(p.x() - (a.x() + f * dx), p.y() - (a.y() + f * dy)))
        return best

    def geometry(self) -> QgsGeometry:
        return QgsGeometry.fromPolylineXY(self.vertices)


def line_from_geometry(geometry: QgsGeometry, crs: QgsCoordinateReferenceSystem) -> Line:
    """The first part of a line geometry as a Line. A multi-part line is read part by part by the caller."""
    parts = geometry.asMultiPolyline() if geometry.isMultipart() else [geometry.asPolyline()]
    parts = [p for p in parts if len(p) >= 2]
    if not parts:
        raise ValueError("the feature is not a line")
    return Line([to_wgs84(QgsPointXY(p), crs) for p in parts[0]])


STATION_FIELDS = ("station:integer", "distance_m:double", "longitude:double", "latitude:double", "method:string(40)",
                  "spacing_m:double", "verdict:string(40)", "signal_noise:double", "library:string(20)")


def station_layer(line: Line, distances, plan: dict, library: str, name: str = "Detectability stations") -> QgsVectorLayer:
    """A point layer in memory, one point a station, in WGS84. Nothing is written to disk."""
    layer = QgsVectorLayer("Point?crs=" + WGS84 + "".join("&field=" + f for f in STATION_FIELDS), name, "memory")
    features = []
    for i, d in enumerate(distances, 1):
        p = line.point_at(d)
        f = QgsFeature(layer.fields())
        f.setGeometry(QgsGeometry.fromPointXY(p))
        f.setAttributes([i, float(d), p.x(), p.y(), plan["name"], plan["spacing_m"], plan["verdict"], plan["snr"], library])
        features.append(f)
    layer.dataProvider().addFeatures(features)
    layer.updateExtents()
    return layer
