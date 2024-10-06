FROM python:3.11-slim@sha256:edaf703dce209d774af3ff768fc92b1e3b60261e7602126276f9ceb0e3a96874

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
