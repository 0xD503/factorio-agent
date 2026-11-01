# Development container for factorio-agent. Not part of the release archives.
#
# The host needs only a container engine, a POSIX shell and git. This image adds
# Python 3.10 (the oldest supported version, so the tests run against it; CI
# covers newer ones), git, the GitHub CLI for releases, and the formatters:
# ruff for Python and StyLua for Lua.
#
# Factorio is not included: it is proprietary. compose.yaml mounts the
# developer's own copy (a Linux build, such as the free headless server)
# read-only at /opt/factorio.
FROM docker.io/library/python:3.10-slim-trixie

ARG USERNAME=dev
ARG USER_UID=1000
ARG USER_GID=1000
ARG RUFF_VERSION=0.17.1
ARG STYLUA_VERSION=2.6.0
# SHA-256 of the StyLua release archives:
ARG STYLUA_X64=a485f72bbfa22e4642e77a84b5edc2611a5cab7477b34e2e709dd8f78e919895
ARG STYLUA_A64=8e67539e5fdf7a81cd03cf592b0df18d3bb96ee17a5ea5d9bf67b86387b903b0

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates curl gh git less openssh-client unzip xz-utils \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir --disable-pip-version-check \
        "ruff==${RUFF_VERSION}"

RUN set -eu; \
    arch=$(uname -m); \
    case "$arch" in \
        x86_64) sum="$STYLUA_X64" ;; \
        aarch64) sum="$STYLUA_A64" ;; \
        *) echo "no StyLua build for $arch" >&2; exit 1 ;; \
    esac; \
    base=https://github.com/JohnnyMorganz/StyLua/releases/download; \
    curl -fsSL -o /tmp/stylua.zip \
        "$base/v${STYLUA_VERSION}/stylua-linux-${arch}.zip"; \
    echo "$sum  /tmp/stylua.zip" | sha256sum -c -; \
    unzip -q /tmp/stylua.zip -d /usr/local/bin; \
    rm /tmp/stylua.zip; \
    stylua --version

RUN groupadd --gid "$USER_GID" "$USERNAME" \
    && useradd --uid "$USER_UID" --gid "$USER_GID" --create-home \
        --shell /bin/bash "$USERNAME"

USER $USERNAME
