"""兼容原有 main:app 入口；开发时也可以执行 python main.py。"""

from app import create_app

app = create_app()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=12082, reload=True)
