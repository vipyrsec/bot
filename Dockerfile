FROM python:3.12-slim@sha256:ad48727987b259854d52241fac3bc633574364867b8e20aec305e6e7f4028b26

# Define Git SHA build argument for Sentry
ARG git_sha="development"
ENV GIT_SHA=$git_sha

COPY requirements/requirements.txt .
RUN python -m pip install --requirement requirements.txt

COPY pyproject.toml pyproject.toml
COPY src/ src/
RUN python -m pip install .

RUN adduser --disabled-password bot
USER bot

CMD [ "python", "-m", "bot" ]
