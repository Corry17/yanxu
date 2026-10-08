"""使用 python -m backend 启动本地工作台。"""
import uvicorn

if __name__ == '__main__':
    uvicorn.run('backend.app:app', host='127.0.0.1', port=8775, workers=1)
