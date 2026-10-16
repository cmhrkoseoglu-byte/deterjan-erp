# Üretim nginx imajı: derlenmiş SPA + TLS sonlandırma + backend'e ters vekil.
# Derleme bağlamı depo köküdür (docker-compose.prod.yml: context: ., dockerfile: nginx/Dockerfile);
# bağlama girecek dosyalar nginx/Dockerfile.dockerignore ile sınırlıdır.
#
# Kurumsal vekil sunucu TLS'i kendi sertifikasıyla açıyorsa (npm için) ek CA paketi isteğe bağlı
# bir derleme sırrıyla verilebilir; verilmezse etkisi yoktur:
#   docker build --secret id=extra_ca,src=/yol/ca-bundle.crt -f nginx/Dockerfile .

FROM node:22-alpine AS build
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN --mount=type=secret,id=extra_ca,required=false \
    if [ -s /run/secrets/extra_ca ]; then export NODE_EXTRA_CA_CERTS=/run/secrets/extra_ca; fi; \
    npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM nginx:1.27-alpine
RUN rm -f /etc/nginx/conf.d/default.conf
COPY nginx/prod/conf.d/ /etc/nginx/conf.d/
COPY nginx/prod/snippets/ /etc/nginx/snippets/
COPY nginx/prod/templates/ /etc/nginx/templates/
COPY --chmod=0755 nginx/prod/docker-entrypoint.d/05-deterjan-erp.sh /docker-entrypoint.d/
COPY --from=build /src/frontend/dist/ /usr/share/nginx/html/
