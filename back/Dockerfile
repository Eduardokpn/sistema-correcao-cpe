FROM python:3.12-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        gcc \
        g++ \
        libgl1 \
        libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./requirements.txt
RUN pip install --upgrade pip \
    && pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8001

# Creates/updates the schema before the API starts. Run through `sh` so it does
# not depend on the file's executable bit surviving the checkout.
ENTRYPOINT ["sh", "/app/docker-entrypoint.sh"]
CMD ["uvicorn", "api.app:app", "--host", "0.0.0.0", "--port", "8001"]
