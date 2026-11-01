"""Writing the agent's in-game script into save files.

The script travels inside the save (control.lua and agent/*.lua), like a
scenario script, so the mod list stays untouched and players who join download
it with the map: nobody has to install a mod. Factorio runs it in its Lua
sandbox, which has no file or network access.
"""

import os
import shutil
import zipfile
from pathlib import Path

from fxa import paths

# Script folders of this and earlier versions of the harness; all are replaced.
OURS = ("agent/", "claude/")


class SaveError(Exception):
    pass


def scripts(lua_dir=paths.LUA):
    found = {
        p.relative_to(lua_dir).as_posix(): p.read_bytes()
        for p in sorted(Path(lua_dir).rglob("*.lua"))
    }
    if "control.lua" not in found:
        raise SaveError(f"{lua_dir} has no control.lua")
    return found


def inject(save_path, lua_dir=paths.LUA, target=None):
    """Replace the scripts inside a save (in place, or into `target`) with the
    ones from lua/.

    The map and the script's stored state are kept. The server must not be
    running on that save.
    """
    save_path = Path(save_path)
    ours = scripts(lua_dir)
    target = Path(target) if target else save_path
    temp = target.with_name(target.name + ".tmp")
    try:
        with (
            zipfile.ZipFile(save_path) as source,
            zipfile.ZipFile(temp, "w", zipfile.ZIP_DEFLATED) as out,
        ):
            names = source.namelist()
            if not names or "/" not in names[0]:
                raise SaveError(
                    f"{save_path} does not look like a Factorio save"
                )
            top = names[0].split("/", 1)[0]
            for info in source.infolist():
                inner = (
                    info.filename.split("/", 1)[1]
                    if "/" in info.filename
                    else info.filename
                )
                if inner == "control.lua" or inner.startswith(OURS):
                    continue
                out.writestr(info, source.read(info.filename))
            for inner, data in ours.items():
                out.writestr(f"{top}/{inner}", data)
    except zipfile.BadZipFile as err:
        temp.unlink(missing_ok=True)
        raise SaveError(f"{save_path}: {err}") from None
    os.replace(temp, target)
    return sorted(ours)


def has_agent(save_path):
    with zipfile.ZipFile(save_path) as z:
        return any(
            name.split("/", 1)[-1].startswith("agent/") for name in z.namelist()
        )


def copy_in(source, saves_dir, name):
    """Copy a save from elsewhere into a session and give it the agent's
    scripts."""
    dest = Path(saves_dir) / f"{paths.check_name(name, 'save name')}.zip"
    if dest.exists():
        raise SaveError(f"{dest} already exists")
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, dest)
    inject(dest)
    return dest
