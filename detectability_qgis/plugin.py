"""The plugin object QGIS loads: one menu entry and one dock panel."""
from __future__ import annotations

from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtWidgets import QAction

MENU = "Detectability"


class DetectabilityPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.panel = None
        self.provider = None

    def initGui(self):  # noqa: N802  (the name QGIS calls)
        self.action = QAction("Detectability: will the survey see the target?", self.iface.mainWindow())
        self.action.setCheckable(True)
        self.action.triggered.connect(self.toggle)
        self.iface.addPluginToMenu(MENU, self.action)
        from qgis.core import QgsApplication

        from .processing_provider import DetectabilityProvider

        self.provider = DetectabilityProvider()
        QgsApplication.processingRegistry().addProvider(self.provider)

    def unload(self):
        if self.provider is not None:
            from qgis.core import QgsApplication

            QgsApplication.processingRegistry().removeProvider(self.provider)
            self.provider = None
        if self.panel is not None:
            self.panel.close_map()
            self.iface.removeDockWidget(self.panel)
            self.panel.deleteLater()
            self.panel = None
        if self.action is not None:
            self.iface.removePluginMenu(MENU, self.action)
            self.action = None

    def toggle(self, checked: bool = True):
        if self.panel is None:
            from .panel import DetectabilityPanel      # imported late: QGIS starts faster, errors show on first use

            self.panel = DetectabilityPanel(self.iface)
            self.panel.visibilityChanged.connect(self.action.setChecked)
            self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.panel)
        self.panel.setVisible(bool(checked))
