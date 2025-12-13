# runtime

Element: EARTH

Runtime is the foundation layer. It must be stable, dependency-light, and deterministic.

## Responsibilities

1) Bootstrapping
  - ensure required directories exist
  - initialize logs
  - provide minimal configuration defaults

2) Concurrency
  - thread pool warm pool
  - controlled background execution
  - no runaway threads

3) Health
  - boot health checks
  - simple pass/fail gates for higher layers

## Required modules

runtime/bootstrap.py
  - init_runtime_environment(base)
  - init_logging(path)

runtime/warm_pool.py
  - WarmPool thread executor wrapper

runtime/health.py
  - HealthChecks.* methods used by app/main.py

## Invariants

1) EARTH initializes before WATER, WOOD, FIRE, METAL.
2) Runtime must not import app/ mutation engines.
3) Runtime must not perform governance logic. That belongs to security/.
4) Runtime must remain usable under Android constraints.

## Logging

reports/health.log is created during init_logging.
runtime must not write to security/ledger.

## Android constraints

Keep all modules standard-library only.
Avoid OS-specific features that break on Android.
Avoid resource limits and heavy subprocess reliance in EARTH.
