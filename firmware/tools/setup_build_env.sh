#!/usr/bin/env bash
# =============================================================================
# setup_build_env.sh - rebuild the arduino-cli compile environment described in
# firmware/BUILD_ENV.md (ESP32-S3 / esp32:esp32@3.3.11) from a fresh container.
#
# Idempotent: re-running skips whatever is already in place.
#
#   firmware/tools/setup_build_env.sh            # set up (server is stopped at the end)
#   SP=/some/dir firmware/tools/setup_build_env.sh
#   ACLI_INDEX_PORT=18765 firmware/tools/setup_build_env.sh
#
# Resulting layout (matches BUILD_ENV.md, so its commands work verbatim):
#   $SP/arduino-cli              arduino-cli binary
#   $SP/acli-data                ARDUINO_DIRECTORIES_DATA (indexes, cores, tools, config)
#   $SP/acli-user                ARDUINO_DIRECTORIES_USER
#   $SP/acli-serve               files served by the temporary localhost index server
#
# Network background (Claude Code cloud container):
#   reachable : github.com, objects.githubusercontent.com, raw.githubusercontent.com
#   blocked   : downloads.arduino.cc, arduino.cc, dl.espressif.com, espressif.com
# Every workaround below exists because of that block list.  TLS verification
# and HTTPS_PROXY are left untouched (the agent proxy's CA is in the system store).
# =============================================================================
set -euo pipefail

SP="${SP:-/tmp/claude-0/-home-user-claude-code-book-template/a0987823-e1ef-5733-8f68-0fdc6df5afdd/scratchpad}"
ACLI_VERSION="${ACLI_VERSION:-1.2.2}"   # BUILD_ENV.md notes are written against 1.2.2
CORE_VERSION="${CORE_VERSION:-3.3.11}"
PORT="${ACLI_INDEX_PORT:-18765}"

ACLI="$SP/arduino-cli"
SERVE="$SP/acli-serve"
DL="$SP/acli-dl"
export ARDUINO_DIRECTORIES_DATA="$SP/acli-data"
export ARDUINO_DIRECTORIES_USER="$SP/acli-user"
DATA="$ARDUINO_DIRECTORIES_DATA"
BASE_URL="http://127.0.0.1:$PORT"

log() { printf '\n==> %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

mkdir -p "$SP" "$SERVE" "$DL" "$DATA" "$ARDUINO_DIRECTORIES_USER"

# -----------------------------------------------------------------------------
# 1. System ctags.
#    WHY: arduino-cli normally downloads its own Arduino-fork ctags
#    (builtin:ctags 5.8-arduino11) from downloads.arduino.cc, which is blocked.
#    We use Ubuntu's universal-ctags instead (apt mirrors are reachable) and
#    point builtin:ctags at it through a wrapper (step 3).  Universal ctags
#    does not emit the "returntype:" field, so prototypes generated for
#    functions defined in a .ino are broken -> mindclip.ino must not contain
#    function definitions (see BUILD_ENV.md).
# -----------------------------------------------------------------------------
SYS_CTAGS="$(command -v ctags-universal || command -v ctags-exuberant || true)"
if [ -z "$SYS_CTAGS" ]; then
  log "Installing universal-ctags via apt"
  command -v apt-get >/dev/null || die "no ctags and no apt-get; install a ctags manually"
  SUDO=""; [ "$(id -u)" -eq 0 ] || SUDO="sudo"
  $SUDO apt-get update -qq
  DEBIAN_FRONTEND=noninteractive $SUDO apt-get install -y -qq universal-ctags >/dev/null
  SYS_CTAGS="$(command -v ctags-universal || command -v ctags-exuberant || true)"
  [ -n "$SYS_CTAGS" ] || die "ctags still not found after apt install"
fi
log "System ctags: $SYS_CTAGS"

# -----------------------------------------------------------------------------
# 2. arduino-cli binary from GitHub releases (arduino.cc download pages are
#    blocked).  Verified against the release's published SHA-256 list.
# -----------------------------------------------------------------------------
if [ -x "$ACLI" ] && "$ACLI" version 2>/dev/null | grep -q "Version: $ACLI_VERSION "; then
  log "arduino-cli $ACLI_VERSION already present"
else
  log "Downloading arduino-cli $ACLI_VERSION from GitHub releases"
  tgz="arduino-cli_${ACLI_VERSION}_Linux_64bit.tar.gz"
  rel="https://github.com/arduino/arduino-cli/releases/download/v$ACLI_VERSION"
  curl -fsSL -o "$DL/$tgz" "$rel/$tgz"
  curl -fsSL -o "$DL/checksums.txt" "$rel/${ACLI_VERSION}-checksums.txt"
  (cd "$DL" && grep " $tgz\$" checksums.txt | sha256sum -c -) || die "arduino-cli checksum mismatch"
  rm -rf "$DL/acli-x" && mkdir -p "$DL/acli-x"
  tar -xzf "$DL/$tgz" -C "$DL/acli-x" arduino-cli
  install -m 0755 "$DL/acli-x/arduino-cli" "$ACLI"
  "$ACLI" version
fi

# -----------------------------------------------------------------------------
# 3. Package indexes + stub archives, all written into $SERVE.
#
#    package_esp32_index.json
#      Espressif's index, fetched from raw.githubusercontent.com (the official
#      URL on espressif.github.io / dl.espressif.com is not reachable).  Any
#      tool needed by esp32@$CORE_VERSION whose download URL is on a blocked
#      host is redirected to a stub archive with rewritten size/checksum.  As of
#      3.3.11 every esp32 tool lives on GitHub, so normally nothing is rewritten.
#
#    package_stubs_index.json
#      Replaces what the main Arduino index (downloads.arduino.cc, blocked)
#      would provide:
#        builtin:ctags            -> wrapper exec'ing the system ctags
#        builtin:serial-discovery -> minimal pluggable-discovery that reports
#        builtin:mdns-discovery      no ports (platform.txt *requires* both or
#                                    the esp32 platform fails to load at all)
#        builtin:serial-monitor   -> stub (monitor unusable; not needed here)
#        arduino:dfu-util         -> stub (esp32 core declares it as a tool
#                                    dependency; only used for some uploads)
#      None of these is used by `arduino-cli compile` except ctags.
#
#    Why an HTTP server at all: arduino-cli downloads index files and tool
#    archives through its own HTTP client, so the stubs must be reachable by
#    URL.  Once installed nothing is fetched again, so `compile` works with the
#    server stopped (the script stops it on exit).
# -----------------------------------------------------------------------------
log "Fetching esp32 package index from raw.githubusercontent.com"
curl -fsSL -o "$DL/package_esp32_index.orig.json" \
  https://raw.githubusercontent.com/espressif/arduino-esp32/gh-pages/package_esp32_index.json

log "Generating stub archives and rewritten indexes"
python3 -I - "$DL/package_esp32_index.orig.json" "$SERVE" "$BASE_URL" "$CORE_VERSION" "$SYS_CTAGS" <<'PY'
import hashlib, io, json, os, sys, tarfile
from urllib.parse import urlparse

orig, serve, base, core_ver, sys_ctags = sys.argv[1:6]
ALLOWED = {"github.com", "objects.githubusercontent.com", "raw.githubusercontent.com"}
HOSTS = ["x86_64-linux-gnu", "x86_64-pc-linux-gnu"]

def script(body):
    return ("#!/bin/sh\n" + body).encode()

FAIL = lambda name: script(
    f'echo "{name}: stub installed by firmware/tools/setup_build_env.sh '
    f'(real tool is on a blocked host)" >&2\nexit 1\n')

# Pluggable discovery protocol v1, answering with an empty port list.
DISCOVERY = script(r'''while IFS= read -r cmd; do
  case "$cmd" in
    HELLO*)      echo '{"eventType":"hello","protocolVersion":1,"message":"OK"}' ;;
    START_SYNC*) echo '{"eventType":"start_sync","message":"OK"}' ;;
    START*)      echo '{"eventType":"start","message":"OK"}' ;;
    LIST*)       echo '{"eventType":"list","ports":[]}' ;;
    STOP*)       echo '{"eventType":"stop","message":"OK"}' ;;
    QUIT*)       echo '{"eventType":"quit","message":"OK"}'; exit 0 ;;
    *)           echo '{"eventType":"command_error","error":true,"message":"unknown command"}' ;;
  esac
done
''')

CTAGS = script(f'# builtin:ctags replacement -> system ctags (not the Arduino fork)\nexec "{sys_ctags}" "$@"\n')

def make_stub(fname, topdir, files):
    """Deterministic tar.gz (fixed mtime/owner) so checksums are stable across runs."""
    raw = io.BytesIO()
    with tarfile.open(fileobj=raw, mode="w", format=tarfile.USTAR_FORMAT) as tf:
        d = tarfile.TarInfo(topdir); d.type = tarfile.DIRTYPE; d.mode = 0o755
        tf.addfile(d)
        for name, data in files.items():
            ti = tarfile.TarInfo(f"{topdir}/{name}"); ti.size = len(data); ti.mode = 0o755
            tf.addfile(ti, io.BytesIO(data))
    import gzip
    gz = io.BytesIO()
    with gzip.GzipFile(fileobj=gz, mode="wb", mtime=0, filename="") as g:
        g.write(raw.getvalue())
    blob = gz.getvalue()
    with open(os.path.join(serve, fname), "wb") as f:
        f.write(blob)
    return {"url": f"{base}/{fname}", "archiveFileName": fname,
            "checksum": "SHA-256:" + hashlib.sha256(blob).hexdigest(), "size": str(len(blob))}

def systems(entry):
    return [dict(host=h, **entry) for h in HOSTS]

# ---- stubs index (stands in for downloads.arduino.cc's package_index.json) ----
stub_tools = {
    ("builtin", "ctags", "5.8-arduino11"): {"ctags": CTAGS},
    ("builtin", "serial-discovery", "1.4.1"): {"serial-discovery": DISCOVERY},
    ("builtin", "mdns-discovery", "1.0.9"): {"mdns-discovery": DISCOVERY},
    ("builtin", "serial-monitor", "0.14.1"): {"serial-monitor": FAIL("serial-monitor")},
    ("arduino", "dfu-util", "0.11.0-arduino5"): {"dfu-util": FAIL("dfu-util")},
}
pkgs = {}
for (pkg, tool, ver), files in stub_tools.items():
    entry = make_stub(f"stub-{pkg}-{tool}-{ver}.tar.gz", tool, files)
    p = pkgs.setdefault(pkg, {"name": pkg, "maintainer": "local stub", "websiteURL": "",
                              "email": "", "help": {"online": ""}, "platforms": [], "tools": []})
    p["tools"].append({"name": tool, "version": ver, "systems": systems(entry)})
with open(os.path.join(serve, "package_stubs_index.json"), "w") as f:
    json.dump({"packages": list(pkgs.values())}, f, indent=1)

# ---- esp32 index: redirect blocked-host tool downloads to stubs ----
idx = json.load(open(orig))
esp = next(p for p in idx["packages"] if p["name"] == "esp32")
plat = next(p for p in esp["platforms"] if p["version"] == core_ver)
need = {(d["name"], d["version"]) for d in plat["toolsDependencies"] if d["packager"] == "esp32"}
if urlparse(plat["url"]).hostname not in ALLOWED:
    sys.exit(f"core archive itself is on a blocked host: {plat['url']}")
rewritten = []
for t in esp["tools"]:
    if (t["name"], t["version"]) not in need:
        continue
    for s in t["systems"]:
        if urlparse(s["url"]).hostname in ALLOWED:
            continue
        stub = make_stub(f"stub-esp32-{t['name']}-{t['version']}.tar.gz", t["name"],
                         {t["name"]: FAIL(t["name"])})
        s.update(stub)
        rewritten.append(f"{t['name']}@{t['version']} ({s['host']})")
with open(os.path.join(serve, "package_esp32_index.json"), "w") as f:
    json.dump(idx, f)
print("esp32 tools redirected to stubs:", ", ".join(sorted(set(rewritten))) or "none")
PY

# -----------------------------------------------------------------------------
# 4. arduino-cli config and placeholder indexes.
#    WHY placeholders: arduino-cli always wants package_index.json and
#    library_index.json from downloads.arduino.cc.  If library_index.json is
#    missing it tries to fetch it on *every* command; if package_index.json is
#    missing every command prints a load error.  Empty valid files silence both
#    (real Arduino AVR/SAMD cores and the library index are simply unavailable).
#    The config lives in $DATA, where arduino-cli looks by default when only
#    ARDUINO_DIRECTORIES_DATA is set, so BUILD_ENV.md's commands need no flags.
# -----------------------------------------------------------------------------
[ -s "$DATA/package_index.json" ] || echo '{"packages":[]}' > "$DATA/package_index.json"
[ -s "$DATA/library_index.json" ] || echo '{"libraries":[]}' > "$DATA/library_index.json"
cat > "$DATA/arduino-cli.yaml" <<EOF
# generated by firmware/tools/setup_build_env.sh
board_manager:
  additional_urls:
    - $BASE_URL/package_esp32_index.json
    - $BASE_URL/package_stubs_index.json
network:
  connection_timeout: 600s
EOF

# -----------------------------------------------------------------------------
# 5. Temporary localhost HTTP server (only for this script's duration).
# -----------------------------------------------------------------------------
SERVER_PID=""
stop_server() {
  if [ -n "$SERVER_PID" ] && kill -0 "$SERVER_PID" 2>/dev/null; then
    kill "$SERVER_PID" 2>/dev/null || true
    wait "$SERVER_PID" 2>/dev/null || true
    echo "(index server on port $PORT stopped)"
  fi
}
trap stop_server EXIT

if curl -fsS -o /dev/null "$BASE_URL/package_stubs_index.json" 2>/dev/null; then
  # Something is already serving on the port; make sure it is serving $SERVE.
  curl -fsS "$BASE_URL/package_stubs_index.json" | cmp -s - "$SERVE/package_stubs_index.json" \
    || die "port $PORT is busy with something else; rerun with ACLI_INDEX_PORT=<free port>"
  log "Reusing index server already running on port $PORT"
else
  log "Starting index server on $BASE_URL"
  python3 -I -m http.server "$PORT" --bind 127.0.0.1 --directory "$SERVE" \
    >"$SP/acli-serve.log" 2>&1 &
  SERVER_PID=$!
  for _ in $(seq 50); do
    curl -fsS -o /dev/null "$BASE_URL/package_stubs_index.json" 2>/dev/null && break
    sleep 0.2
  done
  curl -fsS -o /dev/null "$BASE_URL/package_stubs_index.json" || die "index server did not start (see $SP/acli-serve.log)"
fi

# -----------------------------------------------------------------------------
# 6. Update indexes and install the core.
#    `core update-index` always also tries downloads.arduino.cc and therefore
#    exits non-zero; that failure is expected.  We check the two local indexes
#    actually landed instead of trusting the exit status.
# -----------------------------------------------------------------------------
log "Updating package indexes (the downloads.arduino.cc failure is expected)"
"$ACLI" core update-index || true
for f in package_esp32_index.json package_stubs_index.json; do
  cmp -s "$SERVE/$f" "$DATA/$f" || die "$f was not updated from $BASE_URL"
done

log "Installing esp32:esp32@$CORE_VERSION (large: ~1.5 GB of toolchains from GitHub)"
"$ACLI" core install "esp32:esp32@$CORE_VERSION"

# Builtin tools are installed lazily by instance init; make sure they are there.
"$ACLI" core list >/dev/null
CTAGS_BIN="$DATA/packages/builtin/tools/ctags/5.8-arduino11/ctags"
[ -x "$CTAGS_BIN" ] || die "builtin ctags wrapper missing at $CTAGS_BIN"
# Re-point the wrapper in case the system ctags path changed since it was installed.
printf '#!/bin/sh\n# builtin:ctags replacement -> system ctags (not the Arduino fork)\nexec "%s" "$@"\n' \
  "$SYS_CTAGS" > "$CTAGS_BIN"
chmod 0755 "$CTAGS_BIN"

# Downloaded archives (~1.5 GB) are no longer needed once extracted.
"$ACLI" cache clean

log "Installed cores"
"$ACLI" core list

stop_server
trap - EXIT

cat <<EOF

Done.  Compile with (index server not needed any more):
  SP=$SP
  export ARDUINO_DIRECTORIES_DATA=\$SP/acli-data ARDUINO_DIRECTORIES_USER=\$SP/acli-user
  \$SP/arduino-cli compile -v --warnings all --fqbn esp32:esp32:XIAO_ESP32S3:PSRAM=opi firmware/mindclip
EOF
