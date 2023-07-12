FROM python:3.11-slim@sha256:364ee1a9e029fb7b60102ae56ff52153ccc929ceab9aa387402fe738432d24cc

RUN adduser --disabled-password bot
USER bot

# Define Git SHA build argument for sentry
ARG git_sha="development"
ENV GIT_SHA=$git_sha

WORKDIR /home/bot

COPY requirements.txt .
RUN python -m pip install --requirement requirements.txt

COPY --chown=bot:bot . .
RUN python -m pip install .

CMD ["python", "-m", "bot"]
