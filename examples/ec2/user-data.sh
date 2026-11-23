#!/bin/bash
# EC2 user data for Setup's "Running the proxy on an EC2 instance" (Amazon Linux 2023).
# Runs once, as root, on the instance's first boot.
set -euo pipefail
dnf install -y docker git
systemctl enable --now docker
mkdir -p /usr/local/lib/docker/cli-plugins
curl -fsSL https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64 \
  -o /usr/local/lib/docker/cli-plugins/docker-compose
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
