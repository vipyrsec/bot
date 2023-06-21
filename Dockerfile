FROM python:3.11-slim@sha256:53a67c012da3b807905559fa59fac48a3a68600d73c5da10c2f0d8adc96dbd01

RUN adduser --disabled-password bot
USER bot

ENV PATH="${PATH}:/home/bot/.local/bin"

# Set Git SHA environment variable
ARG git_sha="development"
ENV GIT_SHA=$git_sha

WORKDIR /app
COPY pyproject.toml src ./
RUN python -m pip install .

EXPOSE 8080

CMD ["python", "-m", "bot"]
