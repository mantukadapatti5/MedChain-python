FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt requirements-ml.txt ./
RUN pip install --no-cache-dir -r requirements.txt \
    && pip install --no-cache-dir -r requirements-ml.txt

COPY . .

# Train the ML models at image build time so the API works immediately on
# first boot (skips gracefully / can be re-run later via `docker compose exec`).
RUN python -m app.ml.train_demand && python -m app.ml.train_shortage

RUN chmod +x docker-entrypoint.sh

EXPOSE 5000
ENTRYPOINT ["./docker-entrypoint.sh"]
