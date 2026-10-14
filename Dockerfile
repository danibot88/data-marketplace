FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt "gunicorn>=23,<24"
COPY . .
RUN mkdir -p /app/private_data /app/staticfiles
CMD ["gunicorn", "data_marketplace.wsgi:application", "--bind", "0.0.0.0:8000", "--workers", "3"]
