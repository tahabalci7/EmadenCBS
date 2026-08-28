import os
import re
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
from src.ocr.ocr_engine import OCREngine
from src.coordinate.coordinate_engine import CoordinateEngine
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

        fast_result = OCREngine.extract_text_layer(
            self.current_pdf,
            max_pages=150,
        )

        fast_text = fast_result["text"]

        fast_tables = TableDetector.find_tables(
            fast_text
        )

        fast_coordinates = (
            CoordinateEngine.extract_coordinates(
                fast_text
            )
        )

        fast_polygons = PolygonBuilder.build(
            fast_coordinates
        )

        # -------------------------------------------------
        # ANA HEDEF POLYGON KONTROLÜ
        #
        # OCR'sız okunabilen TÜM polygonlar fast_polygons
        # içinde korunur.
        #
        # Ancak OCR gerekip gerekmediğine yalnızca:
        #   1. Ruhsat alanı
        #   2. ÇED / proje ana alanı
        # bakılarak karar verilir.
        # -------------------------------------------------

        license_types = {
            "RUHSAT_ALANI",
        }

        ced_project_types = {
            "CED_ALANI",
            "MEVCUT_CED_ALANI",
            "YENI_CED_ALANI",
            "PROJE_ALANI",
            "ISLETME_IZIN_ALANI",
        }

        license_polygons = [
            polygon
            for polygon in fast_polygons
            if polygon.get("table_type")
            in license_types
        ]

        ced_project_polygons = [
            polygon
            for polygon in fast_polygons
            if polygon.get("table_type")
            in ced_project_types
        ]

        has_license_polygon = bool(
            license_polygons
        )

        has_ced_project_polygon = bool(
            ced_project_polygons
        )

        # OCR ancak ana hedeflerden biri eksikse gerekir.
        needs_target_ocr = not (
            has_license_polygon
            and has_ced_project_polygon
        )

        # -------------------------------------------------
        # 2. METİN KATMANINDAN HEDEF POLYGON ÇIKTIYSA
        #    OCR YAPMA
        # -------------------------------------------------

        if not needs_target_ocr:
            ocr_result = fast_result

            ocr_result["method"] = (
                "PDF Metin Katmanı "
                "(OCR Gerekmedi)"
            )

            raw_text = fast_text

        else:
            # -------------------------------------------------
            # 3. HEDEF TABLO SAYFALARINI BUL
            #
            # Tesseract burada henüz çalışmıyor.
            # -------------------------------------------------

            import re

            page_pattern = re.compile(
                r"--- Sayfa (\d+) "
                r"\[PDF METİN KATMANI\] ---"
            )

            page_matches = list(
                page_pattern.finditer(
                    fast_text
                )
            )

            target_pages = set()

            area_keywords = (
                "RUHSAT ALANI",
                "RUHSAT SAHASI",
                "ÇED ALANI",
                "CED ALANI",
                "ÇED İZİN",
                "CED IZIN",
                "YENİ ÇED",
                "YENI CED",
                "PROJE ALANI",
                "PROJEYE KONU",
                "TALEP EDİLEN",
                "TALEP EDILEN",
            )

            structure_keywords = (
                "KOORDİNAT",
                "KOORDINAT",
                "UTM",
                "DATUM",
                "SAĞA",
                "SAGA",
                "YUKARI",
                "ENLEM",
                "BOYLAM",
            )

            # -------------------------------------------------
            # HEDEF TABLO BAŞLANGIÇ SAYFALARINI BUL
            # -------------------------------------------------

            for index, match in enumerate(
                page_matches
            ):
                page_number = int(
                    match.group(1)
                )

                start = match.end()

                if (
                    index + 1
                    < len(page_matches)
                ):
                    end = (
                        page_matches[
                            index + 1
                        ].start()
                    )
                else:
                    end = len(
                        fast_text
                    )

                page_text = (
                    fast_text[
                        start:end
                    ].upper()
                )

                has_area = any(
                    keyword in page_text
                    for keyword in area_keywords
                )

                structure_score = sum(
                    1
                    for keyword in structure_keywords
                    if keyword in page_text
                )

                strong_project_heading = (
                    "PROJEYE KONU"
                    in page_text
                    or "TALEP EDİLEN"
                    in page_text
                    or "TALEP EDILEN"
                    in page_text
                )

                # ---------------------------------------------
                # BOZUK METİN KATMANI İÇİN EK SİNYALLER
                #
                # Bazı PDF'lerde Türkçe karakterler ve rakamlar
                # bozuk çözülebilir. Buna rağmen UTM, WGS,
                # ED-50, RUHSAT gibi daha sağlam kelimeler
                # okunabilir.
                # ---------------------------------------------

                has_target_reference = (
                    "RUHSAT" in page_text
                    or "ÇED" in page_text
                    or "CED" in page_text
                    or "PROJE" in page_text
                )

                robust_structure_keywords = (
                    "UTM",
                    "WGS",
                    "ED-50",
                    "ED 50",
                    "SAĞA",
                    "SAGA",
                    "D.O.M",
                    "DOM",
                    "ZON",
                )

                robust_structure_score = sum(
                    1
                    for keyword in robust_structure_keywords
                    if keyword in page_text
                )

                has_table_reference = (
                    "TABLO" in page_text
                )

                # ---------------------------------------------
                # 1. NORMAL, SAĞLAM METİN KATMANI
                # ---------------------------------------------

                if (
                    has_area
                    and structure_score >= 4
                ):
                    target_pages.add(
                        page_number
                    )

                # ---------------------------------------------
                # 2. PROJEYE KONU / TALEP EDİLEN
                # ---------------------------------------------

                elif (
                    strong_project_heading
                    and (
                        "KOORDİNAT"
                        in page_text
                        or "KOORDINAT"
                        in page_text
                    )
                ):
                    target_pages.add(
                        page_number
                    )

                # ---------------------------------------------
                # 3. BOZUK METİN KATMANLI KOORDİNAT TABLOSU
                #
                # Örn. kelimeler bozulmuş olsa bile:
                # RUHSAT + TABLO + UTM + WGS + ED-50
                # güçlü bir koordinat tablosu sinyalidir.
                # ---------------------------------------------

                elif (
                    has_target_reference
                    and has_table_reference
                    and robust_structure_score >= 2
                ):
                    target_pages.add(
                        page_number
                    )

            total_pages = fast_result[
                "page_count"
            ]

            # -------------------------------------------------
            # YAKIN ADAY SAYFALARI AYNI KÜMEYE TOPLA
            #
            # Örnek:
            # 79 ve 80 ayrı ayrı OCR edilmeyecek.
            # Tek küme:
            # [79, 80, 81, 82, 83]
            # -------------------------------------------------
            # -------------------------------------------------
            # ADAY SAYFALARI PUANLA
            #
            # Gerçek koordinat tablosu başlıklarını
            # açıklama / atıf sayfalarından önce dene.
            # -------------------------------------------------

            target_page_scores = {}

            for index, match in enumerate(
                page_matches
            ):
                page_number = int(
                    match.group(1)
                )

                if page_number not in target_pages:
                    continue

                start = match.end()

                if (
                    index + 1
                    < len(page_matches)
                ):
                    end = (
                        page_matches[
                            index + 1
                        ].start()
                    )
                else:
                    end = len(
                        fast_text
                    )

                page_text = (
                    fast_text[
                        start:end
                    ].upper()
                )

                score = 0

                # ---------------------------------------------
                # 1. KOORDİNAT TABLOSU SİNYALİ
                # ---------------------------------------------

                has_coordinate_word = (
                    "KOORDİNAT"
                    in page_text
                    or "KOORDINAT"
                    in page_text
                )

                has_table_word = (
                    "TABLO "
                    in page_text
                )

                if has_coordinate_word:
                    score += 60

                # TABLO tek başına güçlü sinyal değildir.
                # Ancak koordinat ifadesiyle birlikteyse
                # gerçek koordinat tablosu olma ihtimali yüksektir.
                if (
                    has_table_word
                    and has_coordinate_word
                ):
                    score += 40
                # ---------------------------------------------
                # İÇİNDEKİLER / TABLO LİSTESİ CEZASI
                #
                # Raporun başlangıcındaki İçindekiler ve
                # Tablolar Listesi sayfalarında çok sayıda
                # TABLO / RUHSAT / ÇED / KOORDİNAT ifadesi
                # bulunabilir.
                #
                # Bunlar gerçek koordinat tablosu değildir.
                # ---------------------------------------------

                contents_keywords = {
                    "İÇİNDEKİLER",
                    "ICINDEKILER",
                    "İÇİNDEKİLER TABLOSU",
                    "ICINDEKILER TABLOSU",
                    "TABLOLAR LİSTESİ",
                    "TABLOLAR LISTESI",
                    "ÇİZELGELER LİSTESİ",
                    "CIZELGELER LISTESI",
                    "ŞEKİLLER LİSTESİ",
                    "SEKILLER LISTESI",
                }

                if any(
                    keyword in page_text
                    for keyword in contents_keywords
                ):
                    score -= 300
                # ---------------------------------------------
                # 2. RUHSAT ALANI
                # ---------------------------------------------

                has_license_word = (
                    "RUHSAT ALANI"
                    in page_text
                    or "RUHSAT SAHASI"
                    in page_text
                )

                if has_license_word:
                    score += 40

                # Ruhsat + koordinat aynı sayfadaysa
                # çok güçlü hedef sayfa.
                if (
                    has_license_word
                    and has_coordinate_word
                ):
                    score += 60

                # ---------------------------------------------
                # 3. ÇED / PROJE ALANI
                # ---------------------------------------------

                has_ced_word = (
                    "ÇED ALANI"
                    in page_text
                    or "CED ALANI"
                    in page_text
                    or "ÇED İZİN"
                    in page_text
                    or "CED IZIN"
                    in page_text
                    or "YENİ ÇED"
                    in page_text
                    or "YENI CED"
                    in page_text
                )

                has_project_word = (
                    "PROJE ALANI"
                    in page_text
                    or "PROJE ALANLARI"
                    in page_text
                    or "PROJEYE KONU ALAN"
                    in page_text
                    or "İŞLETME İZİN ALANI"
                    in page_text
                    or "ISLETME IZIN ALANI"
                    in page_text
                )

                if has_ced_word:
                    score += 40

                if has_project_word:
                    score += 40

                if (
                    has_coordinate_word
                    and (
                        has_ced_word
                        or has_project_word
                    )
                ):
                    score += 60

                # ---------------------------------------------
                # 4. KOORDİNAT TABLO YAPISI
                # ---------------------------------------------

                structure_score = sum(
                    1
                    for keyword in structure_keywords
                    if keyword in page_text
                )

                score += (
                    structure_score * 10
                )

                # ---------------------------------------------
                # 5. GERÇEK KOORDİNAT SAYISI OKUNABİLİYOR MU?
                #
                # Metin katmanı bozuksa başlıklar okunabilir
                # fakat 6-7 haneli UTM değerleri okunamayabilir.
                # Böyle sayfalar OCR için özellikle değerlidir.
                # ---------------------------------------------

                utm_number_count = len(
                    re.findall(
                        r"\b\d{6,7}(?:[.,]\d+)?\b",
                        page_text,
                    )
                )

                if (
                    has_coordinate_word
                    and utm_number_count >= 4
                ):
                    # Metin katmanı koordinatları da okuyabiliyor.
                    score += 30

                elif (
                    has_coordinate_word
                    and (
                        has_license_word
                        or has_ced_word
                        or has_project_word
                    )
                ):
                    # Başlık güçlü fakat koordinat sayıları
                    # okunamıyor. OCR için çok güçlü aday.
                    score += 80

                # ---------------------------------------------
                # 6. MODELLEME / SONDAJ / REZERV SAYFALARINI
                # GERİYE AT
                # ---------------------------------------------

                negative_keywords = {
                    "SONDAJ",
                    "SONDAJ KOORDİNAT",
                    "SONDAJ KOORDINAT",
                    "MODELLEME",
                    "MODELLEME ÇALIŞMASI",
                    "MODELLEME CALISMASI",
                    "BLOK MODEL",
                    "REZERV HESABI",
                    "REZERV HESAPLAMA",
                    "TENÖR",
                    "TENOR",
                    "JEOLOJİK MODEL",
                    "JEOLOJIK MODEL",
                }

                negative_score = sum(
                    1
                    for keyword in negative_keywords
                    if keyword in page_text
                )

                score -= (
                    negative_score * 40
                )

                # ---------------------------------------------
                # 7. YÖNLENDİRME / AÇIKLAMA SAYFALARI
                # ---------------------------------------------

                if (
                    "EKTE VERİLMEKTEDİR"
                    in page_text
                    or "EKTE VERILMEKTEDIR"
                    in page_text
                ):
                    score -= 50

                target_page_scores[
                    page_number
                ] = score
            # -------------------------------------------------
            # OCR HEDEF SAYFALARINI SINIRLA
            #
            # Büyük ÇED raporlarında modelleme, sondaj,
            # jeoloji vb. bölümlerde çok sayıda koordinat
            # ifadesi bulunabilir.
            #
            # OCR yalnızca en güçlü hedef sayfalarda
            # denenmelidir.
            # -------------------------------------------------

            ranked_targets = sorted(
                target_pages,
                key=lambda page_number: (
                    target_page_scores.get(
                        page_number,
                        0,
                    ),
                    -page_number,
                ),
                reverse=True,
            )
            ranked_targets = sorted(
                target_pages,
                key=lambda page_number: (
                    target_page_scores.get(
                        page_number,
                        0,
                    ),
                    -page_number,
                ),
                reverse=True,
            )

            print(
                "OCR ADAY PUANLARI:",
                [
                    (
                        page_number,
                        target_page_scores.get(
                            page_number,
                            0,
                        ),
                    )
                    for page_number in ranked_targets[:20]
                ],
            )

            # Öncelikle güçlü adayları kullan.
            strong_targets = [
                page_number
                for page_number in ranked_targets
                if target_page_scores.get(
                    page_number,
                    0,
                ) >= 70
            ]
            # Öncelikle güçlü adayları kullan.
            strong_targets = [
                page_number
                for page_number in ranked_targets
                if target_page_scores.get(
                    page_number,
                    0,
                ) >= 70
            ]

            # Güçlü aday yoksa en yüksek puanlı
            # sayfalardan sınırlı sayıda dene.
            if strong_targets:
                sorted_targets = (
                    strong_targets[:12]
                )
            else:
                sorted_targets = (
                    ranked_targets[:12]
                )

            target_groups = []

            for page_number in sorted_targets:
                if not target_groups:
                    target_groups.append(
                        [page_number]
                    )
                    continue

                previous_page = (
                    target_groups[-1][-1]
                )

                if (
                    page_number
                    - previous_page
                    <= 3
                ):
                    target_groups[-1].append(
                        page_number
                    )
                else:
                    target_groups.append(
                        [page_number]
                    )
            # -------------------------------------------------
            # GRUPLARI SIRAYLA OCR ET
            #
            # Ruhsat + ÇED/Proje polygonu elde edildiği
            # anda sonraki gruplara geçme.
            # -------------------------------------------------

            selected_ocr_parts = []
            selected_pages = []

            successful_coordinates = []
            successful_polygons = []

            selected_ocr_result = {
                "success": False,
                "method": "Seçili Sayfalarda OCR",
                "text": "",
                "page_count": total_pages,
                "scanned_pages": 0,
                "text_layer_pages": 0,
                "ocr_pages": 0,
                "failed_pages": 0,
            }

            for group_index, group in enumerate(
                target_groups,
                start=1,
            ):
                # ---------------------------------------------
                # Grubun sonundan 3 sayfa ileriye kadar al.
                #
                # Örnek:
                # [79, 80]
                # ->
                # [79, 80, 81, 82, 83]
                # ---------------------------------------------

                group_pages_set = set()

                for target_page in group:
                    for offset in range(
                        -1,
                        4,
                    ):
                        candidate_page = (
                            target_page
                            + offset
                        )

                        if (
                            1
                            <= candidate_page
                            <= total_pages
                        ):
                            group_pages_set.add(
                                candidate_page
                            )

                group_pages = sorted(
                    group_pages_set
                )

                # Daha önce OCR edilmiş sayfaları tekrar okuma.
                group_pages = [
                    page_number
                    for page_number in group_pages
                    if page_number
                    not in selected_pages
                ]

                if not group_pages:
                    continue

                print(
                    "OCR SAYFALARI:",
                    group_pages,
                )
                group_result = (
                    OCREngine.extract_selected_pages(
                        self.current_pdf,
                        group_pages,
                    )
                )

                selected_pages.extend(
                    group_pages
                )

                selected_ocr_result[
                    "scanned_pages"
                ] += group_result.get(
                    "scanned_pages",
                    0,
                )

                selected_ocr_result[
                    "ocr_pages"
                ] += group_result.get(
                    "ocr_pages",
                    0,
                )

                selected_ocr_result[
                    "failed_pages"
                ] += group_result.get(
                    "failed_pages",
                    0,
                )

                if not group_result[
                    "text"
                ].strip():
                    continue

                selected_ocr_parts.append(
                    group_result["text"]
                )

                cumulative_ocr_text = (
                    "\n".join(
                        selected_ocr_parts
                    )
                )

                # ---------------------------------------------
                # BURADA SADECE OCR METNİNİ TEST EDİYORUZ.
                #
                # Bozuk PDF metin katmanının koordinat
                # parserını etkilemesini istemiyoruz.
                # ---------------------------------------------

                test_coordinates = (
                    CoordinateEngine.extract_coordinates(
                        cumulative_ocr_text
                    )
                )

                test_polygons = (
                    PolygonBuilder.build(
                        test_coordinates
                    )
                )
                # ---------------------------------------------
                # BULUNAN POLYGON TÜRLERİNİ SINIFLANDIR
                # ---------------------------------------------

                has_license = any(
                    polygon.get(
                        "table_type"
                    ) == "RUHSAT_ALANI"
                    for polygon in test_polygons
                )

                has_ced = any(
                    polygon.get(
                        "table_type"
                    )
                    in {
                        "CED_ALANI",
                        "MEVCUT_CED_ALANI",
                        "YENI_CED_ALANI",
                    }
                    for polygon in test_polygons
                )

                has_project = any(
                    polygon.get(
                        "table_type"
                    )
                    in {
                        "PROJE_ALANI",
                        "ISLETME_IZIN_ALANI",
                    }
                    for polygon in test_polygons
                )

                # ---------------------------------------------
                # ANA DURMA KURALI
                #
                # Ruhsat bulundu ve bunun yanında ÇED veya
                # proje/talep alanı bulunduysa yeterlidir.
                # ---------------------------------------------

                if (
                    has_license
                    and (
                        has_ced
                        or has_project
                    )
                ):
                    successful_coordinates = (
                        test_coordinates
                    )

                    successful_polygons = (
                        test_polygons
                    )

                    break

            # -------------------------------------------------
            # SEÇİLİ OCR SONUCUNU TAMAMLA
            # -------------------------------------------------

            selected_ocr_text = "\n".join(
                selected_ocr_parts
            )

            selected_ocr_result[
                "text"
            ] = selected_ocr_text

            selected_ocr_result[
                "success"
            ] = bool(
                selected_ocr_text.strip()
            )

            # Proje sahibi / ruhsat / maden vb. bilgiler için
            # tüm PDF metin katmanı korunur.
            #
            # Koordinatlar için temiz OCR metni sona eklenir.
            raw_text = (
                fast_text
                + "\n"
                + selected_ocr_result["text"]
            )

            ocr_result = {
                "success": (
                    selected_ocr_result[
                        "success"
                    ]
                ),
                "method": (
                    "PDF Metin Katmanı "
                    "+ Seçili Sayfa OCR"
                ),
                "text": raw_text,
                "page_count": (
                    fast_result[
                        "page_count"
                    ]
                ),
                "scanned_pages": (
                    fast_result[
                        "scanned_pages"
                    ]
                ),
                "text_layer_pages": (
                    fast_result.get(
                        "text_layer_pages",
                        0,
                    )
                ),
                "ocr_pages": (
                    selected_ocr_result.get(
                        "ocr_pages",
                        0,
                    )
                ),
                "failed_pages": (
                    selected_ocr_result.get(
                        "failed_pages",
                        0,
                    )
                ),
            }

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

        coordinates = (
            CoordinateEngine.extract_coordinates(
                raw_text
            )
        )

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

        company = project_info.get(
            "company",
            "Proje",
        )

        license_no = project_info.get(
            "license_no",
            "",
        )

        file_name_parts = [
            company,
        ]

        if (
            license_no
            and license_no != "Bilinmiyor"
        ):
            file_name_parts.append(
                license_no
            )

        file_name = "_".join(
            file_name_parts
        )

        file_name = re.sub(
            r'[<>:"/\\|?*]',
            "_",
            file_name,
        )

        file_name = re.sub(
            r"\s+",
            "_",
            file_name,
        ).strip("._ ")

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