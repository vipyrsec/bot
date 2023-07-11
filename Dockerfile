FROM python:3.11-slim@sha256:54065a36b5dfada92010a856935de942425f8f3088a983d150f44db637f92bf8

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
