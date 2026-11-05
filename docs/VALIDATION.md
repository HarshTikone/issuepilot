# Validation record

Validated locally on Windows with Python 3.10.11 during the build session.

| Check | Result |
|---|---|
| `python -m unittest discover -s tests -v` | 40 tests passed |
| `python -m issuepilot --config config.example.json demo` | One simulated job completed; duplicate discovery did not add a second simulated comment |
| CLI help | Commands and arguments load successfully |
| Health HTTP request handling | Liveness, readiness and staleness verified in memory; no live HTTP connectivity claim |

The checks cover durable workflow behavior, crash recovery, ambiguous comment writes, bounded retries, daily start limits, actor identity, source context, schema validation, escaped/encoded credentials, container command restrictions and timeout cleanup.

External GitHub and model behavior is simulated in the local tests. Docker command construction and timeout cleanup are tested using controlled substitutes. This machine did not have a usable Docker/Linux deployment environment available for a real Hermes container run. No SSH server or provider credentials were supplied.

## Required live validation

- [ ] CI passes in the actual GitHub repository, including Ubuntu.
- [ ] Selected pinned Hermes image starts with the configured restrictions.
- [ ] Model/provider authentication and file-tool use work.
- [ ] Real report meets the strict JSON contract and supports its findings.
- [ ] Runtime token can create an issue comment in the chosen repository.
- [ ] Automatic polling picks up a new eligible issue without a manual agent launch.
- [ ] Linux health/readiness endpoints work over local loopback.
- [ ] systemd startup, shutdown cleanup and reboot recovery work on the VPS.

Complete the deployment and evidence guides before describing those items as verified.
