# AI Skill Store — MCP server (stdio transport)
# Glama가 빌드/실행해서 MCP introspection (initialize + tools/list) 통과 여부로 점수 매김.
# 본 컨테이너는 production aiskillstore.io HTTP API 를 백엔드로 사용 — DB 직접 접근 X.

FROM python:3.11-slim

WORKDIR /app

# 시스템 빌드 도구 최소화 (mcp/requests 는 wheel 제공)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# 의존성 먼저 (캐시 활용)
COPY requirements.txt ./
RUN pip install -r requirements.txt

# MCP 서버 코드
COPY mcp_server/ ./mcp_server/

# Backend API endpoint (override 가능)
ENV SKILL_STORE_URL=https://aiskillstore.io

# stdio MCP transport — Glama 표준
CMD ["python", "-u", "mcp_server/skill_store_mcp.py"]
