# -*- coding: utf-8 -*-
# @FileName : run_client.py.py
# @Author   : Tsing Sai
# @Time     : 2026/9/22 20:37
import sys
import os

# 将项目根目录加入Python搜索路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    from client.widgets.login_dialog import LoginDialog
    from client.main_window import ChatMainWindow

    app = QApplication(sys.argv)
    login = LoginDialog()
    if login.exec():
        main_window = ChatMainWindow(login.host, login.nickname, login.tcp_thread)
        main_window.show()
        sys.exit(app.exec())

#打包命令    pyinstaller -F -n 777 run_client.py