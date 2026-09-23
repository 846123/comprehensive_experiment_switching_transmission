# -*- coding: utf-8 -*-
# @FileName : run_server.py.py
# @Author   : Tsing Sai
# @Time     : 2026/9/23 12:49
# -*- coding: utf-8 -*-
# @FileName : run_server.py
# @Author   : Tsing Sai
# @Time     : 2026/9/22 20:37
import sys
import os
import asyncio

# 将项目根目录加入Python搜索路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

if __name__ == "__main__":
    from server.main import main
    asyncio.run(main())


#打包命令  pyinstaller -F -n 局域网视频聊天服务端 run_server.py
