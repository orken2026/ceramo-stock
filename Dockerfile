FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 DATA_DIR=/app/data
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY bot.py storage.py tgstore.py analyze_pdf.py ./
COPY salesreport salesreport

RUN useradd --create-home appuser && mkdir -p /app/data && chown appuser /app/data
USER appuser

CMD ["python", "bot.py"]
