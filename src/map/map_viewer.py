from src.map.layer_manager import LayerManager
from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QBrush, QColor, QPen, QPolygonF
from src.map.layer_manager import LayerManager
from PySide6.QtWidgets import (
    QDialog,
    QGraphicsEllipseItem,
    QGraphicsPolygonItem,
    QGraphicsScene,
    QGraphicsView,
    QLabel,
    QMessageBox,
    QHBoxLayout,
    QVBoxLayout,
)


class MapGraphicsView(QGraphicsView):

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)

        self.setDragMode(
            QGraphicsView.DragMode.ScrollHandDrag
        )

        self.setTransformationAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse
        )

        self.setResizeAnchor(
            QGraphicsView.ViewportAnchor.AnchorUnderMouse
        )

        self.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        self.setSceneRect(
            -5000,
            -5000,
            10000,
            10000,
        )

    def wheelEvent(self, event):
        zoom_in_factor = 1.25
        zoom_out_factor = 1 / zoom_in_factor

        if event.angleDelta().y() > 0:
            factor = zoom_in_factor
        else:
            factor = zoom_out_factor

        self.scale(factor, factor)


class SelectablePolygonItem(QGraphicsPolygonItem):

    def __init__(
        self,
        screen_points,
        polygon_data,
        normal_pen,
        normal_brush,
        selected_pen,
        selected_brush,
        selection_callback,
    ):
        super().__init__(screen_points)

        self.polygon_data = polygon_data
        self.normal_pen = normal_pen
        self.normal_brush = normal_brush
        self.selected_pen = selected_pen
        self.selected_brush = selected_brush
        self.selection_callback = selection_callback

        self.setPen(self.normal_pen)
        self.setBrush(self.normal_brush)

        self.setZValue(1)

        self.setToolTip(
            polygon_data.get(
                "table_type",
                "DIGER"
            )
        )

    def set_selected(self, selected):
        if selected:
            self.setPen(self.selected_pen)
            self.setBrush(self.selected_brush)
            self.setZValue(2)
        else:
            self.setPen(self.normal_pen)
            self.setBrush(self.normal_brush)
            self.setZValue(1)

    def mousePressEvent(self, event):
        event.accept()

        if self.selection_callback:
            self.selection_callback(
                self,
                event.scenePos(),
            )


class CoordinatePointItem(QGraphicsEllipseItem):

    def __init__(
        self,
        x,
        y,
        size,
        point_data,
        polygon_data,
        pen,
        brush,
    ):
        super().__init__(
            x - size / 2,
            y - size / 2,
            size,
            size,
        )

        self.point_data = point_data
        self.polygon_data = polygon_data

        self.setPen(pen)
        self.setBrush(brush)
        self.setZValue(4)

        self.setToolTip(
            f"Nokta: {point_data.get('name', 'Bilinmiyor')}"
        )

    def mousePressEvent(self, event):
        event.accept()

        point_name = self.point_data.get(
            "name",
            "Bilinmiyor"
        )

        utm_y = self.point_data.get(
            "y",
            "Bilinmiyor"
        )

        utm_x = self.point_data.get(
            "x",
            "Bilinmiyor"
        )

        latitude = self.point_data.get(
            "latitude",
            "Bilinmiyor"
        )

        longitude = self.point_data.get(
            "longitude",
            "Bilinmiyor"
        )

        table_type = self.polygon_data.get(
            "table_type",
            "DIGER"
        )

        datum = self.polygon_data.get(
            "datum",
            "Bilinmiyor"
        )

        zone = self.polygon_data.get(
            "zone",
            "Bilinmiyor"
        )

        message = (
            f"Nokta: {point_name}\n\n"
            f"Tablo Türü: {table_type}\n"
            f"UTM Y: {utm_y}\n"
            f"UTM X: {utm_x}\n"
            f"Enlem: {latitude}\n"
            f"Boylam: {longitude}\n"
            f"Datum: {datum}\n"
            f"Zon: {zone}"
        )

        QMessageBox.information(
            None,
            "Koordinat Bilgisi",
            message,
        )

    def mouseReleaseEvent(self, event):
        event.accept()

    def mouseMoveEvent(self, event):
        event.accept()


class MapViewer(QDialog):

    POLYGON_COLORS = [
        QColor("#1565C0"),
        QColor("#C62828"),
        QColor("#2E7D32"),
        QColor("#6A1B9A"),
        QColor("#EF6C00"),
        QColor("#00838F"),
        QColor("#AD1457"),
        QColor("#5D4037"),
    ]

    def __init__(self, polygons, parent=None):
        super().__init__(parent)

        self.polygons = polygons
        self.polygon_items = []
        self.layer_items = []
        self.selected_polygon_item = None

        self.setWindowTitle(
            "eMadenCBS - Polygon Önizleme"
        )
        self.resize(1000, 750)

        self.scene = QGraphicsScene(self)

        self.view = MapGraphicsView(
            self.scene,
            self,
        )

        self.info_label = QLabel(
            "Bir polygon seçmek için alanın içine tıklayın."
        )

        self.info_label.setWordWrap(True)

        self.info_label.setMinimumHeight(70)

        main_layout = QHBoxLayout(self)

        self.layer_manager = LayerManager()
        self.layer_manager.load_layers(self.polygons)
        self.layer_manager.layer_changed_callback = (
            self.layer_visibility_changed
        )
        self.layer_manager.setMaximumWidth(220)

        right_layout = QVBoxLayout()
        right_layout.addWidget(self.view)
        right_layout.addWidget(self.info_label)

        main_layout.addWidget(self.layer_manager)
        main_layout.addLayout(right_layout)

        self.draw_polygons()

    def draw_polygons(self):
        self.scene.clear()
        self.polygon_items.clear()
        self.layer_items.clear()
        self.selected_polygon_item = None

        all_points = []

        for polygon in self.polygons:
            for point in polygon.get("points", []):
                longitude = point.get("longitude")
                latitude = point.get("latitude")

                if longitude is None or latitude is None:
                    continue

                all_points.append(
                    (
                        float(longitude),
                        float(latitude),
                    )
                )

        if not all_points:
            self.info_label.setText(
                "Çizilebilecek koordinat bulunamadı."
            )
            return

        longitudes = [
            point[0]
            for point in all_points
        ]

        latitudes = [
            point[1]
            for point in all_points
        ]

        min_lon = min(longitudes)
        max_lon = max(longitudes)
        min_lat = min(latitudes)
        max_lat = max(latitudes)

        width = 850.0
        height = 600.0
        margin = 50.0

        lon_range = max(
            max_lon - min_lon,
            0.000001,
        )

        lat_range = max(
            max_lat - min_lat,
            0.000001,
        )

        for polygon_index, polygon in enumerate(
            self.polygons,
            start=1,
        ):
            screen_points = QPolygonF()

            valid_points = []

            for point in polygon.get("points", []):
                longitude = point.get("longitude")
                latitude = point.get("latitude")

                if longitude is None or latitude is None:
                    continue

                x = (
                    margin
                    + (
                        (
                            float(longitude)
                            - min_lon
                        )
                        / lon_range
                    )
                    * width
                )

                y = (
                    margin
                    + (
                        (
                            max_lat
                            - float(latitude)
                        )
                        / lat_range
                    )
                    * height
                )

                screen_points.append(
                    QPointF(x, y)
                )

                valid_points.append(point)

            if len(screen_points) < 3:
                continue

            color = self.POLYGON_COLORS[
                (polygon_index - 1)
                % len(self.POLYGON_COLORS)
            ]

            normal_pen = QPen(color)
            normal_pen.setWidth(3)

            normal_fill_color = QColor(color)
            normal_fill_color.setAlpha(70)

            normal_brush = QBrush(
                normal_fill_color
            )

            selected_pen = QPen(color)
            selected_pen.setWidth(6)

            selected_fill_color = QColor(color)
            selected_fill_color.setAlpha(150)

            selected_brush = QBrush(
                selected_fill_color
            )

            polygon_item = SelectablePolygonItem(
                screen_points=screen_points,
                polygon_data=polygon,
                normal_pen=normal_pen,
                normal_brush=normal_brush,
                selected_pen=selected_pen,
                selected_brush=selected_brush,
                selection_callback=self.select_polygon,
            )

            self.scene.addItem(
                polygon_item
            )

            self.polygon_items.append(
                polygon_item
            )

            layer_info = {
                "table_type": polygon.get(
                    "table_type",
                    "DIGER",
                ),
                "polygon": polygon_item,
                "points": [],
                "labels": [],
                "title": None,
            }

            self.layer_items.append(
                layer_info
            )

            first_point = screen_points[0]

            title_item = self.scene.addText(
                f"{polygon_index} - "
                f"{polygon.get('table_type', 'DIGER')}"
            )

            title_item.setPos(
                first_point.x(),
                first_point.y(),
            )

            title_item.setZValue(5)
            layer_info["title"] = title_item

            for point_index, screen_point in enumerate(
                screen_points,
                start=1,
            ):
                point_data = valid_points[
                    point_index - 1
                ]

                point_item = CoordinatePointItem(
                    x=screen_point.x(),
                    y=screen_point.y(),
                    size=8,
                    point_data=point_data,
                    polygon_data=polygon,
                    pen=normal_pen,
                    brush=QBrush(color),
                )

                self.scene.addItem(
                    point_item
                )
                layer_info["points"].append(
                    point_item
                )

                label = point_data.get(
                    "name",
                    str(point_index),
                )

                label_item = self.scene.addText(
                    str(label)
                )

                label_item.setPos(
                    screen_point.x() + 5,
                    screen_point.y() - 15,
                )

                label_item.setZValue(5)
                layer_info["labels"].append(
                    label_item
                )

        self.scene.setSceneRect(
            0,
            0,
            width + margin * 2,
            height + margin * 2,
        )

        self.draw_legend()

        self.view.fitInView(
            self.scene.sceneRect(),
            Qt.AspectRatioMode.KeepAspectRatio,
        )

    def select_polygon(
        self,
        clicked_item,
        scene_position,
    ):
        overlapping_items = []

        for polygon_item in self.polygon_items:
            local_position = polygon_item.mapFromScene(
                scene_position
            )

            if polygon_item.contains(local_position):
                overlapping_items.append(
                    polygon_item
                )

        if not overlapping_items:
            return

        if (
            self.selected_polygon_item
            in overlapping_items
        ):
            current_index = overlapping_items.index(
                self.selected_polygon_item
            )

            next_index = (
                current_index + 1
            ) % len(overlapping_items)

            selected_item = overlapping_items[
                next_index
            ]
        elif clicked_item in overlapping_items:
            selected_item = clicked_item
        else:
            selected_item = overlapping_items[0]

        if (
            self.selected_polygon_item is not None
            and self.selected_polygon_item
            is not selected_item
        ):
            self.selected_polygon_item.set_selected(
                False
            )

        self.selected_polygon_item = selected_item
        selected_item.set_selected(True)

        polygon = selected_item.polygon_data

        table_type = polygon.get(
            "table_type",
            "DIGER"
        )

        section = polygon.get(
            "section",
            "Bilinmeyen Alan"
        )

        point_count = polygon.get(
            "point_count",
            len(polygon.get("points", [])),
        )

        datum = polygon.get(
            "datum",
            "Bilinmiyor"
        )

        geographic_datum = polygon.get(
            "geographic_datum",
            "Bilinmiyor"
        )

        zone = polygon.get(
            "zone",
            "Bilinmiyor"
        )

        dom = polygon.get(
            "dom",
            "Bilinmiyor"
        )

        projection = polygon.get(
            "projection",
            "Bilinmiyor"
        )

        overlap_count = len(
            overlapping_items
        )

        overlap_text = ""

        if overlap_count > 1:
            overlap_text = (
                f"\nBu noktada {overlap_count} polygon "
                f"çakışıyor. Tekrar tıklayarak "
                f"diğerine geçebilirsiniz."
            )

        self.info_label.setText(
            f"Seçilen Polygon: {table_type}\n"
            f"Bölüm: {section}\n"
            f"Nokta Sayısı: {point_count} | "
            f"UTM Datum: {datum} | "
            f"Coğrafi Datum: {geographic_datum} | "
            f"Zon: {zone} | "
            f"DOM: {dom} | "
            f"Projeksiyon: {projection}"
            f"{overlap_text}"
        )

        table_type = polygon.get(
            "table_type",
            "DIGER"
        )

        section = polygon.get(
            "section",
            "Bilinmeyen Alan"
        )

        point_count = polygon.get(
            "point_count",
            len(polygon.get("points", [])),
        )

        datum = polygon.get(
            "datum",
            "Bilinmiyor"
        )

        geographic_datum = polygon.get(
            "geographic_datum",
            "Bilinmiyor"
        )

        zone = polygon.get(
            "zone",
            "Bilinmiyor"
        )

        dom = polygon.get(
            "dom",
            "Bilinmiyor"
        )

        projection = polygon.get(
            "projection",
            "Bilinmiyor"
        )

        self.info_label.setText(
            f"Seçilen Polygon: {table_type}\n"
            f"Bölüm: {section}\n"
            f"Nokta Sayısı: {point_count} | "
            f"UTM Datum: {datum} | "
            f"Coğrafi Datum: {geographic_datum} | "
            f"Zon: {zone} | "
            f"DOM: {dom} | "
            f"Projeksiyon: {projection}"
        )

    def draw_legend(self):
        legend_x = (
            self.scene.sceneRect().right()
            - 220
        )

        legend_y = (
            self.scene.sceneRect().top()
            + 20
        )

        for legend_index, polygon in enumerate(
            self.polygons,
            start=1,
        ):
            color = self.POLYGON_COLORS[
                (legend_index - 1)
                % len(self.POLYGON_COLORS)
            ]

            y_position = (
                legend_y
                + (
                    (legend_index - 1)
                    * 30
                )
            )

            legend_box = self.scene.addRect(
                legend_x,
                y_position,
                18,
                18,
                QPen(color),
                QBrush(color),
            )

            legend_box.setZValue(6)

            legend_text = polygon.get(
                "table_type",
                "DIGER"
            )

            text_item = self.scene.addText(
                legend_text
            )

            text_item.setPos(
                legend_x + 26,
                y_position - 4,
            )

            text_item.setZValue(6)
    def layer_visibility_changed(
        self,
        layer_name,
        visible,
    ):
        for layer in self.layer_items:

            if layer["table_type"] != layer_name:
                continue

            layer["polygon"].setVisible(
                visible
            )

            if layer["title"] is not None:
                layer["title"].setVisible(
                    visible
                )

            for point in layer["points"]:
                point.setVisible(
                    visible
                )

            for label in layer["labels"]:
                label.setVisible(
                    visible
                )