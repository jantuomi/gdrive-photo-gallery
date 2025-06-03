FROM alpine
RUN apk add --no-cache python3 uv

WORKDIR /app
COPY pyproject.toml .python-version uv.lock /app/
RUN uv sync

COPY static /app/static
COPY templates /app/templates
COPY app.py /app/

EXPOSE 8000

CMD ["uv", "run", "gunicorn", "--bind", "0.0.0.0:8000", "app:app", "-w", "1"]
