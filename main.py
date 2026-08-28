import sys
from PySide6.QtWidgets import QApplication
from src.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)

    app.setApplicationName("eMadenCBS Professional")
    app.setOrganizationName("eMadenCBS")

    window = MainWindow()
    window.show()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()