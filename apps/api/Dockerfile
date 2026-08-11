# 后端。用官方 uv 镜像，因为项目本来就用 uv 管依赖——
# 在容器里换成 pip 会让锁文件失去意义，两处依赖迟早对不上。
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

# 先只拷依赖描述，让这一层能被缓存：改一行业务代码不该重装一遍依赖。
COPY apps/api/pyproject.toml apps/api/uv.lock ./
RUN uv sync --frozen --no-install-project

COPY apps/api/ ./
COPY scripts/ /repo/scripts/
RUN uv sync --frozen

ENV PATH="/app/.venv/bin:$PATH" PYTHONUNBUFFERED=1

EXPOSE 8000
CMD ["/app/entrypoint.sh"]
