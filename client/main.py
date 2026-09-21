import sys
from PyQt6.QtWidgets import QApplication
from .widgets.login_dialog import LoginDialog
from .main_window import ChatMainWindow


if __name__ == "__main__":
    app = QApplication(sys.argv)
    login = LoginDialog()
    if login.exec():
        main_window = ChatMainWindow(login.host, login.nickname, login.tcp_thread)
        main_window.show()
        sys.exit(app.exec())
