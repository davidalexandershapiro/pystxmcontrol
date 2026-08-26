# STXM MCP + Claude Code — a portable container for users to write (and run)
# acquisition scripts with an AI assistant, isolated to a mounted scripts folder.
# The point of the container is FILESYSTEM isolation (Layer-3): users cannot edit
# repository code or host system files — only the mounted /work folder is visible.
# Hardware access is intentionally UNRESTRICTED by default: the full MCP toolset is
# available and scripts run against the live control server.
#
# Everything site-specific is injected at runtime — control-server address (env),
# API key (env), scripts folder (volume) — so the same image deploys anywhere.
#
# Build (from the repo root — build context must be the repo root).
# pystxm-core is a PRIVATE repo, so a GitHub token is passed as a BuildKit secret
# (never baked into an image layer — see the pystxm_core stage below):
#   export GITHUB_TOKEN=$(gh auth token)   # or a PAT with repo scope
#   DOCKER_BUILDKIT=1 docker build --secret id=gh_token,env=GITHUB_TOKEN \
#     -f docker/Dockerfile -t stxm-mcp:latest .
# Example build:
# DOCKER_BUILDKIT=1 docker build --secret id=gh_token,env=GITHUB_TOKEN \
#   -f <path to docker file> -t <docker username>/<image name> <path to pystxmcontrol>

# One-time host preparation of the scripts folder.  The container runs as
# uid 1000 / gid 801 (cosmic) and a bind mount passes those numeric ids straight
# through, so the folder must be writable by that group or every write the agent
# attempts fails with EACCES — which looks exactly like a read-only mount:
#   sudo chgrp -R cosmic /srv/stxm/scripts
#   sudo chmod -R g+ws  /srv/stxm/scripts     # g+s: new files stay in the group
#
# Saved energy definitions (list_energy_presets / update_scan(energy_preset=...)) live
# in the host's pystxmcontrol_cfg — i.e. under the GUI environment's sys.prefix, NOT in
# the repo.  The container's own sys.prefix is /usr/local, so it finds nothing unless
# that directory is mounted and pointed at explicitly:
#     -v <sys.prefix>/pystxmcontrol_cfg:/opt/stxm/pystxmcontrol_cfg:ro \
#     -e PYSTXM_CFG_DIR=/opt/stxm/pystxmcontrol_cfg
# Find <sys.prefix> with:  python -c "import sys; print(sys.prefix)"  in the GUI env.
#
# That directory also contains main.json with the staff-password hash/salt.  To share
# ONLY the presets, mount the presets subfolder instead and use the narrower override:
#     -v <sys.prefix>/pystxmcontrol_cfg/energy_presets:/opt/stxm/energy_presets:ro \
#     -e PYSTXM_ENERGY_PRESETS_DIR=/opt/stxm/energy_presets
# (Favorites pinned in the dashboard live in the cfg dir itself, so that narrower form
#  sees only the presets saved as files.  PYSTXM_ENERGY_FAVORITES_JSON can add them.)
#
# Run — FULL access (default; Claude can move motors / run scans via MCP):
#   docker run -it --rm --network host \
#     -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
#     -e PYSTXM_SERVER_HOST=131.243.191.90 -e PYSTXM_SERVER_PORT=9999 \
#     -v /srv/stxm/scripts:/work \
#     -v /srv/stxm/pystxmcontrol_cfg:/opt/stxm/pystxmcontrol_cfg:ro \
#     -e PYSTXM_CFG_DIR=/opt/stxm/pystxmcontrol_cfg \
#     stxm-mcp:latest
#
# Run — READ-ONLY MCP (opt-in; drops move_motor/stxm_scan from Claude's tools).
# NOTE this only limits Claude's direct tool calls; a script that is executed still
# reaches the hardware via the scripter (its own control-server connection).
#   docker run ... -e PYSTXM_MCP_READONLY=1 ...  stxm-mcp:latest
#
# Only /work (the mounted scripts folder) is visible from the host; the container
# cannot reach other repos, beamline data, or the host filesystem.

FROM python:3.12-slim

# ---- Node.js + Claude Code CLI ----
RUN apt-get update && apt-get install -y --no-install-recommends \
        curl ca-certificates git \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @anthropic-ai/claude-code \
    && apt-get purge -y curl && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# ---- MCP runtime deps ONLY (verified set — none of the repo's GUI/hardware stack) ----
# NOTE: pin mcp to 1.x — the 2.0 release removed mcp.server.fastmcp, which server.py imports.
RUN pip install --no-cache-dir "mcp==1.26.0" pyzmq pydantic numpy matplotlib h5py

# ---- pystxm_core: currently a PRIVATE repo. A BuildKit secret carries a GitHub
#      token into the build WITHOUT baking it into any image layer. Once the repo
#      is public on PyPI, drop the secret and replace this with the plain PyPI name.
#
#      Build (from the repo root):
#        export GITHUB_TOKEN=$(gh auth token)   # or a PAT with repo scope
#        DOCKER_BUILDKIT=1 docker build --secret id=gh_token,env=GITHUB_TOKEN \
#          -f docker/Dockerfile -t dashapiro76/pystxmcontrol-mcp .
ARG PYSTXM_CORE_REF="david/refactor"
RUN --mount=type=secret,id=gh_token \
    pip install --no-cache-dir \
    "git+https://$(cat /run/secrets/gh_token)@github.com/als-computing/pystxm-core.git@${PYSTXM_CORE_REF}"

# ---- MCP server code on PYTHONPATH (NO `pip install .` → skips the monolithic
#      GUI/hardware dependency set that fails headless). Only the mcp/controller
#      subtree is needed, but copying the package is simplest and still light. ----
COPY pystxmcontrol/ /opt/stxm/pystxmcontrol/
COPY docker/mcp.json docker/settings.json /opt/stxm/
ENV PYTHONPATH=/opt/stxm \
    MPLBACKEND=Agg

# ---- non-root user; /work is the mount point for the site's scripts folder ----
# The container user's group MUST match the beamline's: files it writes into the
# mounted scripts folder have to be readable AND writable by beamline staff, and a
# bind mount carries numeric ids straight through — the host has no idea what
# "stxm" means, it only sees uid 1000 / gid 801.  cosmic (gid 801) is therefore
# stxm's PRIMARY group, so everything the agent creates in /work is group-owned by
# cosmic whether or not the host directory carries the setgid bit.
#
# The host side must allow the group to write (see the run examples above):
#   sudo chgrp -R cosmic /srv/stxm/scripts
#   sudo chmod -R g+ws  /srv/stxm/scripts     # g+s: new files stay in the group
RUN groupadd -g 801 cosmic \
    && useradd -m -u 1000 -g cosmic stxm
USER stxm
WORKDIR /work

# Launch claude in the scripts folder with the READ-ONLY MCP profile.
# --strict-mcp-config ignores any .mcp.json a user drops into /work, so the tool
# surface can't be widened from inside the container.
#
# umask 002 makes agent-written scripts group-writable (664/775) instead of the
# default 644 — without it beamline staff could read an agent-written script but
# not edit it in place.  "$@" forwards any extra `docker run` arguments to claude.
ENTRYPOINT ["sh", "-c", \
            "umask 002 && exec claude \"$@\"", "--", \
            "--mcp-config", "/opt/stxm/mcp.json", \
            "--strict-mcp-config", \
            "--settings", "/opt/stxm/settings.json"]
