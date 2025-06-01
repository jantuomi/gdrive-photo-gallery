FROM alpine
RUN apk add --no-cache python3 uv

WORKDIR /app
COPY static /app/static
COPY templates /app/templates
COPY app.py pyproject.toml .python-version uv.lock /app/
RUN uv sync

CMD ["uv", "run", "gunicorn", "--bind", "0.0.0.0:8000", "app:app", "-w", "1"]
