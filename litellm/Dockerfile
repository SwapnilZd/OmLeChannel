FROM python:3.12-slim

WORKDIR /app

COPY source_content/certs/ /usr/local/share/ca-certificates/
RUN apt-get update \
    && apt-get install --no-install-recommends -y libatomic1 \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
ENV REQUESTS_CA_BUNDLE=/etc/ssl/certs/ca-certificates.crt

RUN pip install --no-cache-dir "litellm[proxy,proxy-runtime]==1.93.0" "prisma==0.11.0"
RUN prisma generate --schema=/usr/local/lib/python3.12/site-packages/litellm/proxy/schema.prisma

ENTRYPOINT ["litellm"]
