FROM python:3.13-slim

WORKDIR /app

COPY requirements.txt requirements-push.txt ./

RUN pip install --no-cache-dir -r requirements.txt -r requirements-push.txt

COPY . .

ENV PORT=8000

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT}"]
