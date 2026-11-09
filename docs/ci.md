# Jolt as a CI gate

Jolt exits with status 1 when a run scores below `--min-score`. A pipeline can therefore stop a change that makes the system less resilient, the same way a failing unit test does.

## Gate a live run

`jolt run` needs a QNX 8.0 target reachable over SSH and QNX SDP 8.0 on the build machine. On GitHub that means a self-hosted runner, for example the Linux or WSL2 host from [`setup/SETUP.md`](../setup/SETUP.md), with the QEMU VM running.

```yaml
# .github/workflows/resilience.yml
name: resilience
on: [pull_request]
jobs:
  jolt:
    runs-on: [self-hosted, qnx]          # a host with QNX SDP 8.0 and `ssh qnxvm` working
    steps:
      - uses: actions/checkout@v4
      - name: Build and deploy the system under test
        run: target/build.sh qnxvm
      - name: Inject faults and score
        run: |
          python3 -m jolt run --target qnxvm --only imu,planner,actuator,watchdog --seed 1 \
            --reset "sh /tmp/jolt/stack.sh start-fixed" --out jolt-out/ci --min-score 100
      - name: Keep the evidence
        if: always()
        uses: actions/upload-artifact@v4
        with:
          name: jolt-report
          path: jolt-out/ci/
```

- Exit status 1 from `jolt run` fails the job.
- `junit.xml` lists one test case per check, so any CI system that reads JUnit shows each failure by name.
- `report.md` has the fix for each failing check.
- The fixed seed means a rerun of the same commit injects the same faults in the same order.

## Gate a recorded run

`jolt check` reads an existing `report.json` and needs no target. This repository's own CI uses it on the recorded runs in [`jolt-out/`](../jolt-out/), so the gate logic is tested on every push:

```bash
python -m jolt check --run jolt-out/after  --min-score 100   # passes: 100/100
python -m jolt check --run jolt-out/before --min-score 100   # fails: 29/100, lists the 5 failing checks
```

A run where no check was exercised (score n/a) fails `jolt check` unless you pass `--allow-unexercised`. This stops an empty run from passing silently.
