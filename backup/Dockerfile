# Yedekleme servisi: pg_dump/pg_restore (PostgreSQL 16 istemcisi, sunucuyla aynı ana sürüm),
# busybox crond ile zamanlanmış yedek ve geri yükleme testi, rclone ile isteğe bağlı uzak kopya.
FROM postgres:16-alpine

RUN apk add --no-cache bash jq rclone tzdata coreutils findutils

ENV TZ=Europe/Istanbul
# Medya volume'ü boşken ilk bağlayan konteyner sahipliği bu klasörden alır; yedekleme servisi
# backend'den önce başlasa da volume uygulama kullanıcısına (UID 10001, backend/Dockerfile) ait olur.
RUN rm -rf /media && mkdir /media && chown 10001:10001 /media
COPY --chmod=0755 lib.sh backup.sh restore-test.sh restore.sh entrypoint.sh /backup/

ENTRYPOINT ["/backup/entrypoint.sh"]
CMD ["cron"]
