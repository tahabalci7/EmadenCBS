from PySide6.QtWidgets import QFileDialog


class PDFLoader:

    @staticmethod
    def choose_pdf(parent):

        file_name, _ = QFileDialog.getOpenFileName(
            parent,
            "PDF Seç",
            "",
            "PDF Dosyaları (*.pdf)"
        )

        return file_name