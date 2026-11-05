FROM python:3.12-slim

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY app app
COPY web web
COPY check_1c.py .

RUN useradd --create-home appuser
USER appuser

CMD ["sh", "-c", "exec uvicorn --factory app.main:build_app --host 0.0.0.0 --port ${PORT:-8000} --no-access-log"]
