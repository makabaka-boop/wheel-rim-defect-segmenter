FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /workspace

COPY requirements.txt /tmp/requirements.txt
COPY backend/requirements.txt /tmp/backend-requirements.txt
RUN pip install --no-cache-dir \
    -r /tmp/requirements.txt \
    -r /tmp/backend-requirements.txt

COPY backend ./backend
COPY tests ./tests
COPY pytest.ini ./pytest.ini

CMD ["pytest", "-q"]
