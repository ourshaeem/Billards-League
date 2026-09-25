# Billiards & Ping Pong League API - production image.
#
# Build and run it from the repository root:
#   docker build -t league-api Backend
#   docker run --rm -p 5000:5000 --env-file Backend/.env league-api
#
# All configuration comes from environment variables (Backend/.env.example
# lists them); at least DATABASE_URL and JWT_SECRET_KEY are required.
# Nothing secret is baked into the image.

FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    APP_ENV=production \
    PORT=5000

WORKDIR /app

# Dependencies before the code, so a code change doesn't reinstall them.
# Every one ships as a prebuilt wheel, so no compiler is needed.
COPY requirements.txt .
RUN pip install -r requirements.txt

# Amazon's certificate bundle for RDS. With it, the connection to the
# database is encrypted and the server is checked to really be RDS - see
# ssl_ca in the DATABASE_URL template in .env.example.
RUN mkdir -p /app/certs \
 && python -c "import urllib.request; urllib.request.urlretrieve('https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem', '/app/certs/rds-global-bundle.pem')"

COPY . .

# Run as an ordinary user, not root.
RUN useradd --no-create-home --shell /usr/sbin/nologin --uid 10001 app
USER app

EXPOSE 5000

# gunicorn reads PORT, so the host can pick the port; 5000 otherwise.
ENTRYPOINT ["gunicorn", "--config", "gunicorn.conf.py"]
CMD ["app:app"]
