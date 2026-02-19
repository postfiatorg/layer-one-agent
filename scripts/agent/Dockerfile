FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    cron \
    curl \
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
       -o /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" \
       > /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y --no-install-recommends gh \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY crontab /etc/cron.d/agent-cron
RUN chmod 0644 /etc/cron.d/agent-cron && crontab /etc/cron.d/agent-cron

COPY entrypoint.sh .
RUN chmod +x entrypoint.sh

COPY src/ src/

RUN mkdir -p /data

ENV GH_TOKEN=""
ENV GITHUB_TOKEN=""

ENTRYPOINT ["./entrypoint.sh"]
