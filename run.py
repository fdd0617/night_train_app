"""独立启动脚本，可直接执行: python run.py"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from night_train_app.app import app
from night_train_app.config import Config

if __name__ == "__main__":
    print(f"🌙 夜行列车推荐已启动：http://127.0.0.1:{Config.PORT}")
    app.run(host="127.0.0.1", port=Config.PORT, debug=Config.DEBUG)
