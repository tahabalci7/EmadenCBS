from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QListWidget,
    QListWidgetItem,
)


class LayerManager(QListWidget):

    def __init__(self, parent=None):
        super().__init__(parent)

        self.layer_changed_callback = None

    def load_layers(self, polygons):
        self.clear()

        added = set()

        for polygon in polygons:

            layer = polygon.get(
                "table_type",
                "DIGER"
            )

            if layer in added:
                continue

            added.add(layer)

            item = QListWidgetItem(layer)

            item.setFlags(
                item.flags()
                | Qt.ItemFlag.ItemIsUserCheckable
            )

            item.setCheckState(
                Qt.CheckState.Checked
            )

            self.addItem(item)

        self.itemChanged.connect(
            self.layer_changed
        )

    def layer_changed(self, item):

        if self.layer_changed_callback:
            self.layer_changed_callback(
                item.text(),
                item.checkState()
                == Qt.CheckState.Checked
            )