# Development container for factorio-agent. Not part of the release archives.
#
# The host needs only a container engine (Docker or Podman), a POSIX shell and git to clone.
# Everything else is here: Python 3.10 (the oldest supported version, so the tests run against
# it; CI covers newer ones), git, the GitHub CLI for releases, and the free Factorio headless
# server for `fx selftest`, verified against the checksums Factorio publishes.
FROM docker.io/library/python:3.10-slim-bookworm

ARG FACTORIO_VERSION=stable
ARG USERNAME=dev
ARG USER_UID=1000
ARG USER_GID=1000

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git gh less openssh-client xz-utils \
    && rm -rf /var/lib/apt/lists/*

RUN set -eu; \
    cd /tmp; \
    url=$(curl -fsSL -o headless.tar.xz -w '%{url_effective}' "https://factorio.com/get-download/${FACTORIO_VERSION}/headless/linux64"); \
    name=$(basename "${url%%\?*}"); \
    want=$(curl -fsSL https://factorio.com/download/sha256sums/ | awk -v n="$name" '$2 == n {print $1}'); \
    test -n "$want" || { echo "no published checksum for $name" >&2; exit 1; }; \
    echo "$want  headless.tar.xz" | sha256sum -c -; \
    tar -xJf headless.tar.xz -C /opt; \
    rm headless.tar.xz; \
    /opt/factorio/bin/x64/factorio --version | head -1

RUN groupadd --gid "$USER_GID" "$USERNAME" \
    && useradd --uid "$USER_UID" --gid "$USER_GID" --create-home --shell /bin/bash "$USERNAME"

# The harness finds the server through this; there is no game client in the container.
ENV FACTORIO_SERVER=/opt/factorio
USER $USERNAME
