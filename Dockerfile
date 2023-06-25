FROM python:3.11-slim@sha256:eaee5f73efa9ae962d2077756292bc4878c04fcbc13dc168bb00cc365f35647e

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
