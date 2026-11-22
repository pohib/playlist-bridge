FROM python:3.12-slim-trixie
RUN apt-get update && apt-get upgrade -y --no-install-recommends && rm -rf /var/lib/apt/lists/*
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN groupadd --system app && useradd --system --gid app --home-dir /app app
COPY requirements.txt .
RUN python -m pip install --no-cache-dir --upgrade 'pip>=26.2.0,<27' 'setuptools>=83.0.0,<84' && python -m pip install --no-cache-dir -r requirements.txt && rm -rf /usr/local/lib/python3.12/site-packages/setuptools-70.*.dist-info && python -c "import setuptools; from packaging.version import Version; assert Version(setuptools.__version__) >= Version('83.0.0')" && python -m pip check
COPY --chown=app:app . .
RUN mkdir -p /app/staticfiles && chown -R app:app /app
USER app
EXPOSE 8000
CMD ["gunicorn","config.wsgi:application","--bind","0.0.0.0:8000","--workers","2","--timeout","180"]
