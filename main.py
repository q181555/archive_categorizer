"""
archive_categorizer/main.py - 入口文件

用法：
  python main.py               # 启动图形界面
  python main.py --help        # 显示帮助
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui import main

if __name__ == "__main__":
    main()
