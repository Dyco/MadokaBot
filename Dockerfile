FROM python:3.12 AS requirements_stage

ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

WORKDIR /wheel

RUN python -m pip install --user pipx

COPY ./pyproject.toml \
  ./requirements.txt \
  /wheel/


RUN --mount=type=cache,target=/root/.cache/pip \
    python -m pip wheel \
    --wheel-dir=/wheel \
    --requirement ./requirements.txt

RUN python -m pipx run --no-cache nb-cli generate -f /tmp/bot.py


FROM node:24-bookworm-slim AS node_runtime

FROM python:3.12-slim

ENV PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

WORKDIR /app

ENV TZ Asia/Shanghai
ENV PYTHONPATH=/app

COPY ./docker/gunicorn_conf.py ./docker/start.sh /
COPY --from=node_runtime /usr/local/bin/node /usr/local/bin/node

RUN sed -i \
    -e 's|deb.debian.org|mirrors.tuna.tsinghua.edu.cn|g' \
    -e 's|security.debian.org|mirrors.tuna.tsinghua.edu.cn|g' \
    /etc/apt/sources.list.d/debian.sources

RUN chmod +x /start.sh \
  && apt-get update \
  && apt-get install -y --no-install-recommends \
      ffmpeg \
      libatomic1 \
      libstdc++6 \
  && rm -rf /var/lib/apt/lists/* \
  && node --version

ENV APP_MODULE _main:app
ENV MAX_WORKERS 1

COPY --from=requirements_stage /tmp/bot.py /app
COPY ./docker/_main.py /app
COPY --from=requirements_stage /wheel /wheel

RUN pip install --no-cache-dir gunicorn uvicorn[standard] nonebot2 \
  && pip install --no-cache-dir --no-index --force-reinstall --find-links=/wheel -r /wheel/requirements.txt && rm -rf /wheel

# 在构建时安装 Chromium 与系统依赖，避免启动时下载失败。
RUN python -m playwright install --with-deps chromium \
  && rm -rf /var/lib/apt/lists/*

COPY . /app/

CMD ["/start.sh"]
