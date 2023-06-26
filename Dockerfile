FROM python:3.11-slim@sha256:53a67c012da3b807905559fa59fac48a3a68600d73c5da10c2f0d8adc96dbd01

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
