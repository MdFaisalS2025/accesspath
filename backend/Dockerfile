FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Shell form (not exec-array form) so $PORT is substituted at container
# start -- Render assigns its own dynamic port via this env var and routes
# traffic to it; local Docker Compose never sets PORT, so this still
# defaults to 8000 exactly as before (docker-compose.yml's "8000:8000"
# port mapping is unaffected).
CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --reload
