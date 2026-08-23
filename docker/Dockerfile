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
# Build (from the repo root — build context must be the repo root):
#   docker build -f docker/Dockerfile -t stxm-mcp:latest .
#
# Run — FULL access (default; Claude can move motors / run scans via MCP):
#   docker run -it --rm --network host \
#     -e ANTHROPIC_API_KEY="$ANTHROPIC_API_KEY" \
#     -e PYSTXM_SERVER_HOST=131.243.191.90 -e PYSTXM_SERVER_PORT=9999 \
#     -v /srv/stxm/scripts:/work \
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
RUN pip install --no-cache-dir mcp pyzmq pydantic numpy matplotlib h5py

# ---- pystxm_core: currently a PRIVATE repo. Until it is public on PyPI this needs
#      build-time credentials (or vendor a wheel and COPY it in). Once public,
#      replace the git spec with the plain PyPI name.
ARG PYSTXM_CORE_SPEC="git+https://github.com/als-computing/pystxm-core.git@david/refactor"
RUN pip install --no-cache-dir "${PYSTXM_CORE_SPEC}"

# ---- MCP server code on PYTHONPATH (NO `pip install .` → skips the monolithic
#      GUI/hardware dependency set that fails headless). Only the mcp/controller
#      subtree is needed, but copying the package is simplest and still light. ----
COPY pystxmcontrol/ /opt/stxm/pystxmcontrol/
COPY docker/mcp.json docker/settings.json /opt/stxm/
ENV PYTHONPATH=/opt/stxm \
    MPLBACKEND=Agg

# ---- non-root user; /work is the mount point for the site's scripts folder ----
RUN useradd -m -u 1000 stxm
USER stxm
WORKDIR /work

# Launch claude in the scripts folder with the READ-ONLY MCP profile.
# --strict-mcp-config ignores any .mcp.json a user drops into /work, so the tool
# surface can't be widened from inside the container.
ENTRYPOINT ["claude", \
            "--mcp-config", "/opt/stxm/mcp.json", \
            "--strict-mcp-config", \
            "--settings", "/opt/stxm/settings.json"]
