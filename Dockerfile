FROM python:3.13-slim@sha256:de14de6e5d3150702e6139018c608c00479bfa24694a4a9fe4ed25243b2fab16

# Define Git SHA build argument for Sentry
ARG git_sha="development"
ENV GIT_SHA=$git_sha

WORKDIR /app

RUN python -m pip install --no-cache-dir -U pip setuptools wheel
RUN python -m pip install --no-cache-dir pdm

COPY pyproject.toml pdm.lock ./
RUN pdm export --prod -o requirements.txt && python -m pip install --no-cache-dir -r requirements.txt

COPY src/ src/
RUN python -m pip install --no-cache-dir .

RUN useradd --no-create-home --shell=/bin/bash bot
USER bot

CMD [ "python", "-m", "bot" ]
