FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    FLASK_RUN_HOST=0.0.0.0 \
    FLASK_RUN_PORT=5000 \
    FLASK_DEBUG=0

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt python-dotenv

COPY app.py models.py ./
COPY templates ./templates
COPY static ./static
COPY instance ./instance

EXPOSE 5000

CMD ["python", "app.py"]
