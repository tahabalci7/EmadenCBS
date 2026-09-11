import os
import time

from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QHBoxLayout,
    QTreeWidget,
    QTreeWidgetItem,
    QTextEdit,
    QStatusBar,
    QToolBar,
    QFileDialog,
    QMessageBox,
)

from PySide6.QtGui import QAction
from PySide6.QtCore import Qt, QSettings
from src.core.pdf_analyzer import PDFAnalyzer
from src.core.pdf_loader import PDFLoader
from src.core.project_manager import ProjectManager
from src.core.pdf_text_extraction_service import (
    PDFTextExtractionService,
)
from src.coordinate.coordinate_engine import CoordinateEngine
from src.coordinate.pipeline_contract import (
    collect_pipeline_diagnostics,
    format_diagnostics_text,
)
from src.coordinate.polygon_builder import PolygonBuilder
from src.coordinate.project_model import ProjectModel
from src.map.map_viewer import MapViewer
from src.coordinate.table_detector import TableDetector
from src.project.project_info_extractor import (
    ProjectInfoExtractor,
)
from src.export.kml_exporter import (
    KMLExporter,
)


class MainWindow(QMainWindow):

    def __init__(self):
        super().__init__()

        self.project_manager = ProjectManager()
        self.project_info_extractor = ProjectInfoExtractor()

        self.current_pdf = None
        self.current_project_model = None

        self.setWindowTitle("eMadenCBS Professional v0.12")
        self.resize(1400, 850)
        self.setAcceptDrops(True)

        self.create_menu()
        self.create_toolbar()
        self.create_ui()

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Hazır")

    def create_menu(self):
        menu = self.menuBar()

        dosya = menu.addMenu("Dosya")

        pdf_ac = QAction("PDF Aç", self)
        pdf_ac.triggered.connect(self.open_pdf)
        dosya.addAction(pdf_ac)

        ocr_action = QAction("OCR + Koordinat Tara", self)
        ocr_action.triggered.connect(self.run_ocr)
        dosya.addAction(ocr_action)

        menu.addMenu("e-ÇED")
        menu.addMenu("PDF")
        cbs_menu = menu.addMenu("CBS")

        show_map_action = QAction("Haritada Göster", self)
        show_map_action.triggered.connect(self.show_map)
        cbs_menu.addAction(show_map_action)
        export_kml_action = QAction(
            "Google Earth KML Dışa Aktar",
            self,
        )

        export_kml_action.triggered.connect(
            self.export_kml
        )

        cbs_menu.addAction(
            export_kml_action
        )
        menu.addMenu("Araçlar")
        menu.addMenu("Yardım")

    def create_toolbar(self):
        toolbar = QToolBar("Araç Çubuğu")
        self.addToolBar(toolbar)

        pdf_ac = QAction("PDF Aç", self)
        pdf_ac.triggered.connect(self.open_pdf)
        toolbar.addAction(pdf_ac)

        ocr_action = QAction("OCR + Koordinat Tara", self)
        ocr_action.triggered.connect(self.run_ocr)
        toolbar.addAction(ocr_action)

    def create_ui(self):
        central = QWidget()
        central.setAcceptDrops(True)
        self.setCentralWidget(central)

        layout = QHBoxLayout(central)

        self.project_tree = QTreeWidget()
        self.project_tree.setHeaderLabel("Proje")
        self.project_tree.setAcceptDrops(False)

        self.workspace = QTextEdit()
        self.workspace.setReadOnly(True)
        self.workspace.setAcceptDrops(False)

        layout.addWidget(self.project_tree, 1)
        layout.addWidget(self.workspace, 4)

        self.refresh_tree()

    def refresh_tree(self):
        self.project_tree.clear()

        root = QTreeWidgetItem(["eMadenCBS Projesi"])
        pdf_root = QTreeWidgetItem(["📄 PDF Dosyaları"])

        for pdf in self.project_manager.get_pdfs():
            pdf_root.addChild(QTreeWidgetItem([pdf.split("/")[-1]]))

        root.addChild(pdf_root)
        root.addChild(QTreeWidgetItem(["📊 Excel Dosyaları"]))
        root.addChild(QTreeWidgetItem(["📍 Koordinatlar"]))
        root.addChild(QTreeWidgetItem(["🗺 Haritalar"]))
        root.addChild(QTreeWidgetItem(["📝 Çıktılar"]))

        self.project_tree.addTopLevelItem(root)
        self.project_tree.expandAll()

    def show_pdf(self, file_name):
        self.current_pdf = file_name
        self.project_manager.add_pdf(file_name)
        self.refresh_tree()

        result = PDFAnalyzer.analyze(file_name)

        text = ""
        for key, value in result.items():
            text += f"{key} : {value}\n"

        text += "\n"
        text += f"Açık PDF Sayısı : {self.project_manager.pdf_count()}"

        self.workspace.setPlainText(text)
        self.statusBar().showMessage(file_name)

    def open_pdf(self):
        file_name = PDFLoader.choose_pdf(self)

        if not file_name:
            return

        self.show_pdf(file_name)

    def run_ocr(self):
        if not self.current_pdf:
            self.workspace.setPlainText(
                "Önce bir PDF açmalısın."
            )
            return

        total_start = time.perf_counter()

        # -------------------------------------------------
        # 1. HIZLI PDF METİN KATMANI TARAMASI
        # -------------------------------------------------

        step_start = time.perf_counter()

        ocr_result = PDFTextExtractionService.extract(
            self.current_pdf,
            defer_heavy_fallback_if_useful=True,
        )

        raw_text = ocr_result.get(
            "text",
            "",
        )

        ocr_duration = (
            time.perf_counter()
            - step_start
        )

        # -------------------------------------------------
        # 6. NİHAİ TABLO ANALİZİ
        # -------------------------------------------------

        step_start = time.perf_counter()

        tables = TableDetector.find_tables(
            raw_text
        )

        table_duration = (
            time.perf_counter()
            - step_start
        )

        # -------------------------------------------------
        # 7. NİHAİ KOORDİNAT ANALİZİ
        # -------------------------------------------------

        step_start = time.perf_counter()

        extraction = (
            CoordinateEngine.extract_pipeline(
                raw_text,
                pdf_path=self.current_pdf,
                tables=tables,
            )
        )
        coordinates = extraction["coordinates"]

        coordinate_duration = (
            time.perf_counter()
            - step_start
        )

        # -------------------------------------------------
        # 8. POLYGONLAR
        # -------------------------------------------------

        step_start = time.perf_counter()

        polygons = PolygonBuilder.build(
            coordinates
        )

        polygon_duration = (
            time.perf_counter()
            - step_start
        )
        # -------------------------------------------------
        # PROJECT MODEL
        # -------------------------------------------------

        project_model = ProjectModel(
            pdf_path=self.current_pdf,
            coordinates=coordinates,
            polygons=polygons,
            tables=tables,
            diagnostics=collect_pipeline_diagnostics(
                tables,
                coordinates,
                polygons,
                extra=extraction["diagnostics"],
            ),
        )

        # -------------------------------------------------
        # PROJE BİLGİLERİ
        # -------------------------------------------------

        step_start = time.perf_counter()

        project_info = (
            self.project_info_extractor.extract(
                raw_text
            )
        )

        project_info_duration = (
            time.perf_counter()
            - step_start
        )

        project_model.set_project_info(
            project_info
        )

        self.current_project_model = (
            project_model
        )

        # -------------------------------------------------
        # DEBUG METNİ
        # -------------------------------------------------

        step_start = time.perf_counter()

        lines = raw_text.splitlines()

        debug_lines = []

        keywords = [
            "SAĞA",
            "SAGA",
            "YUKARI",
            "KOORDİNAT",
            "KOORDINAT",
            "R.1",
            "R1",
        ]

        for i, line in enumerate(lines):
            upper = line.upper()

            if any(
                keyword in upper
                for keyword in keywords
            ):
                start = max(
                    0,
                    i - 10,
                )

                end = min(
                    len(lines),
                    i + 30,
                )

                debug_lines.append(
                    "\n=============================="
                )

                debug_lines.append(
                    f"Yakalanan Bölge - Satır {i + 1}"
                )

                debug_lines.append(
                    "=============================="
                )

                for j in range(
                    start,
                    end,
                ):
                    debug_lines.append(
                        f"{j + 1}: {lines[j]}"
                    )

        preview_text = raw_text[:5000]

        debug_duration = (
            time.perf_counter()
            - step_start
        )

        total_duration = (
            time.perf_counter()
            - total_start
        )

        # -------------------------------------------------
        # SONUÇ METNİ
        # -------------------------------------------------

        text = (
            "OCR + Koordinat Tarama Sonucu\n\n"
        )

        text += (
            f"Yöntem : "
            f"{ocr_result['method']}\n"
        )

        text += (
            f"Başarılı : "
            f"{'Evet' if ocr_result['success'] else 'Hayır'}\n"
        )

        text += (
            f"Toplam Sayfa : "
            f"{ocr_result['page_count']}\n"
        )

        text += (
            f"Taranan Sayfa : "
            f"{ocr_result['scanned_pages']}\n"
        )

        text += (
            f"Metin Katmanından Alınan : "
            f"{ocr_result.get('text_layer_pages', 0)}\n"
        )

        text += (
            f"OCR Yapılan Sayfa : "
            f"{ocr_result.get('ocr_pages', 0)}\n"
        )

        text += (
            f"Başarısız Sayfa : "
            f"{ocr_result.get('failed_pages', 0)}\n"
        )

        if (
            not ocr_result.get("success", False)
            and ocr_result.get("error")
        ):
            text += (
                f"Hata : "
                f"{ocr_result['error']}\n"
            )

        text += (
            f"Bulunan Koordinat Adayı : "
            f"{project_model.coordinate_count}\n\n"
        )

        text += (
            f"Bulunan Koordinat Tablosu : "
            f"{project_model.table_count}\n"
        )

        text += (
            f"Oluşturulan Polygon Sayısı : "
            f"{project_model.polygon_count}\n\n"
        )

        diagnostics_text = format_diagnostics_text(
            project_model.diagnostics
        )
        if diagnostics_text:
            text += diagnostics_text
            text += "\n"

        # -------------------------------------------------
        # PERFORMANS
        # -------------------------------------------------

        text += "Performans\n"
        text += "----------------\n"

        text += (
            f"OCR / Metin Çıkarma : "
            f"{ocr_duration:.2f} sn\n"
        )

        text += (
            f"Tablo Tespiti       : "
            f"{table_duration:.3f} sn\n"
        )

        text += (
            f"Koordinat Çıkarma   : "
            f"{coordinate_duration:.3f} sn\n"
        )

        text += (
            f"Polygon Oluşturma   : "
            f"{polygon_duration:.3f} sn\n"
        )

        text += (
            f"Proje Bilgileri     : "
            f"{project_info_duration:.3f} sn\n"
        )

        text += (
            f"Debug Hazırlama     : "
            f"{debug_duration:.3f} sn\n"
        )

        text += (
            f"TOPLAM               : "
            f"{total_duration:.2f} sn\n\n"
        )

        # -------------------------------------------------
        # PROJE BİLGİLERİ
        # -------------------------------------------------

        text += "Proje Bilgileri\n"
        text += "----------------\n"

        text += (
            f"Proje Sahibi Ünvanı : "
            f"{project_model.project_info.get('company', 'Bilinmiyor')}\n"
        )

        text += (
            f"Maden Cinsi : "
            f"{project_model.project_info.get('mine_type', 'Bilinmiyor')}\n"
        )

        text += (
            f"Ruhsat No : "
            f"{project_model.project_info.get('license_no', 'Bilinmiyor')}\n"
        )

        text += (
            f"İl : "
            f"{project_model.project_info.get('province', 'Bilinmiyor')}\n"
        )

        text += (
            f"İlçe : "
            f"{project_model.project_info.get('district', 'Bilinmiyor')}\n\n"
        )

        # -------------------------------------------------
        # KOORDİNATLAR
        # -------------------------------------------------

        if coordinates:
            text += "Koordinat Adayları\n"
            text += "------------------\n\n"

            for index, item in enumerate(
                coordinates[:30],
                start=1,
            ):
                text += f"{index})\n"

                text += (
                    f"Satır : "
                    f"{item['line']}\n"
                )

                text += (
                    f"Değer : "
                    f"{item['value']}\n"
                )

                text += (
                    f"Skor  : "
                    f"{item['score']}\n"
                )

                text += (
                    f"Metin : "
                    f"{item['text']}\n"
                )

                text += (
                    f"Tablo Türü : "
                    f"{item.get('table_type', 'DIGER')}\n"
                )

                text += (
                    f"Bölüm : "
                    f"{item.get('section', 'Bilinmeyen Alan')}\n"
                )

                text += (
                    f"Tablo No : "
                    f"{item.get('table_index', 0)}\n"
                )

                text += (
                    f"UTM Datum : "
                    f"{item.get('datum', 'Bilinmiyor')}\n"
                )

                text += (
                    f"Coğrafi Datum : "
                    f"{item.get('geographic_datum', 'Bilinmiyor')}\n"
                )

                text += (
                    f"Zon : "
                    f"{item.get('zone', 'Bilinmiyor')}\n"
                )

                text += (
                    f"DOM : "
                    f"{item.get('dom', 'Bilinmiyor')}\n"
                )

                text += (
                    f"Projeksiyon : "
                    f"{item.get('projection', 'Bilinmiyor')}\n\n"
                )

        # -------------------------------------------------
        # HAM METİN
        # -------------------------------------------------

        text += "PDF BAŞLANGIÇ METNİ\n"
        text += "-------------------\n"
        text += preview_text
        text += "\n\n"

        text += (
            "\n\n--- KOORDİNAT TABLOSU "
            "HAM METİN DEBUG ---\n"
        )

        if debug_lines:
            text += "\n".join(
                debug_lines[:400]
            )
        else:
            text += (
                "SAĞA / YUKARI / KOORDİNAT / "
                "R.1 gibi anahtar kelimeler "
                "ham metinde bulunamadı."
            )

        self.workspace.setPlainText(
            text
        )

        self.statusBar().showMessage(
            f"OCR + koordinat tamamlandı "
            f"({total_duration:.2f} sn)"
        )
    def show_map(self):
        if self.current_project_model is None:
            self.workspace.setPlainText(
                "Önce bir PDF açıp OCR + Koordinat Tara işlemini çalıştırmalısın."
            )
            return

        polygons = self.current_project_model.polygons

        if not polygons:
            self.workspace.setPlainText(
                "Haritada gösterilecek polygon bulunamadı."
            )
            return

        viewer = MapViewer(
            polygons=polygons,
            parent=self,
        )
        viewer.exec()

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            for url in event.mimeData().urls():
                file_path = url.toLocalFile()

                if file_path.lower().endswith(".pdf"):
                    event.acceptProposedAction()
                    return

        event.ignore()

    def dropEvent(self, event):
        if not event.mimeData().hasUrls():
            event.ignore()
            return

        loaded_count = 0

        for url in event.mimeData().urls():
            file_path = url.toLocalFile()

            if file_path.lower().endswith(".pdf"):
                self.show_pdf(file_path)
                loaded_count += 1

        if loaded_count > 0:
            self.statusBar().showMessage(f"{loaded_count} PDF sürükle-bırak ile eklendi")
            event.acceptProposedAction()
        else:
            event.ignore()
    def export_kml(self):
        if self.current_project_model is None:
            QMessageBox.warning(
                self,
                "Uyarı",
                "Önce bir PDF tarayın.",
            )
            return

        settings = QSettings(
            "eMadenCBS",
            "eMadenCBS Professional",
        )

        export_directory = settings.value(
            "kml_export_directory",
            "",
            type=str,
        )

        if (
            not export_directory
            or not os.path.isdir(export_directory)
        ):
            export_directory = (
                QFileDialog.getExistingDirectory(
                    self,
                    "KML Kayıt Klasörünü Seç",
                )
            )

            if not export_directory:
                return

            settings.setValue(
                "kml_export_directory",
                export_directory,
            )

        project_info = getattr(
            self.current_project_model,
            "project_info",
            {},
        )

        file_name = ProjectInfoExtractor.build_export_filename(
            project_info,
            default="Proje",
        )

        file_path = os.path.join(
            export_directory,
            f"{file_name}.kml",
        )

        try:
            KMLExporter.export(
                self.current_project_model,
                file_path,
            )

            QMessageBox.information(
                self,
                "KML Oluşturuldu",
                (
                    "KML dosyası otomatik kaydedildi:\n\n"
                    f"{file_path}"
                ),
            )

        except Exception as error:
            QMessageBox.critical(
                self,
                "KML Dışa Aktarma Hatası",
                str(error),
            )
