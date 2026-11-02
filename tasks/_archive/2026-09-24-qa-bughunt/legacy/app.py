"""Railway 入口文件 - 从 web/app.py 导入 FastAPI 应用"""
from web.app import app

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
