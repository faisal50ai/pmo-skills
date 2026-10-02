FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY examples ./examples
RUN pip install --no-cache-dir . && useradd --uid 10001 --create-home pmo
USER 10001
ENTRYPOINT ["pmo"]
CMD ["report", "examples/project.json"]
