FROM python:3.11-slim@sha256:36b544be6e796eb5caa0bf1ab75a17d2e20211cad7f66f04f6f5c9eeda930ef5

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
