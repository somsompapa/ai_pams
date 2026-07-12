# PAMS 서버 이미지 - 홈서버(라즈베리파이 등)/VPS 공용
#
# 빌드:  docker build -t pams .
# 실행:  docker run -d --name pams -p 8000:8000 \
#          -v $(pwd)/data:/app/data \
#          -e PAMS_MODE=real -e PAMS_PASSWORD=비밀번호 pams
FROM python:3.11-slim

# 한글 PDF 보고서용 폰트
RUN apt-get update \
    && apt-get install -y --no-install-recommends fonts-nanum \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .

COPY config ./config
COPY examples ./examples

ENV PAMS_ROOT=/app \
    PAMS_HOST=0.0.0.0 \
    PAMS_PORT=8000
EXPOSE 8000

CMD ["python", "-m", "pams.interfaces.api"]
