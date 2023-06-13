FROM python:3.11-slim@sha256:4102cb4b15a5c0c52068d3128f87b1d43e6a3b431714f4a65e8b8e91750c7c54

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
