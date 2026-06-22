"""CLI entry point: python -m src.dashboard"""

import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "src.dashboard.app:create_app",
        factory=True,
        host="localhost",
        port=8000,
        reload=False,
    )
