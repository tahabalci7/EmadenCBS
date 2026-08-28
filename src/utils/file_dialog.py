from PySide6.QtWidgets import QFileDialog


def open_pdf(parent=None):
    file_name, _ = QFileDialog.getOpenFileName(
        parent,
        "PDF Seç",
        "",
        "PDF Dosyaları (*.pdf)"
    )

    return file_name