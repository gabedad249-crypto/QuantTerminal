import sys
from PySide6.QtWidgets import QApplication
from app.config import Settings
from app.logger import setup_logging
from app.ui.main_window import MainWindow
from app.ui.theme import QUANT_DARK
from app.utils.paths import ensure_project_dirs


def main() -> int:
    ensure_project_dirs()
    logger = setup_logging()
    settings = Settings().load()
    app = QApplication(sys.argv)
    app.setStyleSheet(QUANT_DARK)
    window = MainWindow(settings, logger)
    window.show()
    return app.exec()

if __name__ == "__main__":
    raise SystemExit(main())
