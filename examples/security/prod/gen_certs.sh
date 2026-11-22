#!/usr/bin/env bash
# Self-signed CA and a localhost server certificate, for the demo only; use your real CA or ACME in production.
set -euo pipefail
cd "$(dirname "$0")" && mkdir -p certs && cd certs
openssl req -x509 -newkey rsa:2048 -nodes -days 30 -subj "/CN=demo-ca" -keyout ca.key -out ca.crt \
  -addext "basicConstraints=critical,CA:TRUE" -addext "keyUsage=critical,keyCertSign,cRLSign" 2>/dev/null
openssl req -newkey rsa:2048 -nodes -subj "/CN=localhost" -keyout server.key -out server.csr 2>/dev/null
printf "subjectAltName=DNS:localhost,IP:127.0.0.1\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nauthorityKeyIdentifier=keyid\n" > san.ext
openssl x509 -req -in server.csr -CA ca.crt -CAkey ca.key -CAcreateserial -days 30 -extfile san.ext -out server.crt 2>/dev/null
chmod 644 ca.crt server.crt server.key   # readable inside the containers; keep real keys 600, owned by the nginx user
rm -f server.csr san.ext ca.srl
echo "wrote $(pwd)/{ca,server}.{crt,key}"
