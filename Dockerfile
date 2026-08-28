FROM python:3.9-slim

ENV TZ=Asia/Shanghai

RUN apt-get update \
    && apt-get install -y --no-install-recommends tzdata \
    && ln -snf /usr/share/zoneinfo/${TZ} /etc/localtime \
    && echo ${TZ} > /etc/timezone \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend/ /app/

# app.py and gunicorn.conf.py write logs here.
RUN mkdir -p /opt/nurse-station/logs

CMD ["gunicorn", "-c", "/app/gunicorn.conf.py", "app:app"]
