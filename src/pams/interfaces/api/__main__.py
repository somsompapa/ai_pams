"""개발 서버 실행: python -m pams.interfaces.api

기본은 내 PC 전용(127.0.0.1). 같은 와이파이의 폰에서 보려면:
  PAMS_HOST=0.0.0.0 make serve  →  폰에서 http://<PC 내부 IP>:8000
"""

import os

import uvicorn

from pams.interfaces.api.app import create_app

if __name__ == "__main__":
    uvicorn.run(
        create_app(),
        host=os.environ.get("PAMS_HOST", "127.0.0.1"),
        port=int(os.environ.get("PAMS_PORT", "8000")),
    )
