FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --uid 10001 sober \
    && chown -R sober:sober /app

USER sober

CMD ["python", "main.py"]
