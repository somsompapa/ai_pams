"""개발 서버 실행: python -m pams.interfaces.api"""

import uvicorn

from pams.interfaces.api.app import create_app

if __name__ == "__main__":
    uvicorn.run(create_app(), host="127.0.0.1", port=8000)
