# ziee-ai/hub — maintainer recipes
#
# `just` runs each recipe from the repo root regardless of where you invoke
# it. Install via `brew install just`.

# Default — list recipes.
default:
    @just --list

# Run the Pages workflow locally via act + Docker. Hard-fails if Docker
# or act are missing. First run pulls ~1-2 GB of runner image; later runs
# finish in under a minute.
test-pages:
    @bash scripts/test-pages-build.sh

# Validate every manifest under models/ assistants/ mcp-servers/.
# No Docker, no network.
validate:
    @python3 scripts/validate.py

# Build dist/ locally without act. Useful for a fast smoke test before
# spinning up Docker.
build-pages:
    @python3 scripts/build-pages.py --version 2.0.0 --out dist

# Wipe locally-generated test/build outputs.
clean:
    @rm -rf dist .act-artifacts .act-run.log
