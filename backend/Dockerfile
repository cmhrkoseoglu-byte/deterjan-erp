# Backend imajı, iki hedef:
#   prod: yalnızca çalışma bağımlılıkları, root olmayan kullanıcı, kaynak kod imajın içinde
#         (docker-compose.prod.yml -> target: prod)
#   dev : geliştirme bağımlılıklarıyla (.[dev]); kaynak kod volume ile bağlanır.
#         SON aşama olduğu için `build: ./backend` (docker-compose.yml) bunu derler.
#
# Kurumsal vekil sunucu (proxy) TLS'i kendi sertifikasıyla açıyorsa ek CA paketi isteğe bağlı
# bir derleme sırrıyla verilebilir; verilmezse hiçbir etkisi yoktur:
#   docker build --secret id=extra_ca,src=/yol/ca-bundle.crt ...

FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# --- üretim ------------------------------------------------------------------------------------
FROM base AS prod

# Sabit UID/GID: medya volume'ü ve yedekten geri yüklenen dosyaların sahibi bu kullanıcıdır.
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --home-dir /app --no-create-home --shell /usr/sbin/nologin app

COPY pyproject.toml ./
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi; \
    pip install "."

# Kaynak kod root'a ait kalır (uygulama kullanıcısı değiştiremez); yazılabilir klasörler ayrı.
COPY . .
# media: ekler (volume), staticfiles: collectstatic çıktısı (migrate servisi yazar, nginx okur),
# /var/lib/celery: Celery Beat zamanlama dosyası. Boş named volume ilk bağlandığında sahipliği
# buradan alır.
RUN mkdir -p /app/media /app/staticfiles /var/lib/celery \
    && chown app:app /app/media /app/staticfiles /var/lib/celery

USER app
EXPOSE 8000
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000", \
     "--workers", "4", "--proxy-headers", "--forwarded-allow-ips=*", "--no-server-header"]

# --- geliştirme (son aşama: varsayılan hedef) -------------------------------------------------
FROM base AS dev

COPY pyproject.toml ./
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export PIP_CERT=/run/secrets/extra_ca; fi; \
    pip install ".[dev]"

COPY . .

EXPOSE 8000
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000"]
