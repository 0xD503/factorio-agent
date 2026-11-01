# Your Factorio goes here

Factorio is proprietary and is not part of this project. The dev container
mounts this folder at /opt/factorio unless `FACTORIO_DIR` in
`.devcontainer/.env` names another one (see `.env.example`).

Put (or extract) a Linux build of Factorio here: the folder that holds `bin/`
and `data/`. The free headless server from https://www.factorio.com/download is
enough for `fx selftest`. Nothing in this folder except this file is tracked by
git.
