# Dispatching the reserved benchmark (owner action, after review)

The reserved workflow `.github/workflows/integration-reserved.yml` is **workflow_dispatch only**. No push, no schedule and no public validation run can start it. It has not been dispatched.

## Preconditions (all checked by the workflow's `guard` job)

1. **Owner approval.** The owner approves the graph set and budget in `integration/benchmark/MANIFEST.json`:
   - all 130 `tests/pace16-hidden` graphs × 3 solvers × 3 policies = 1,170 invocations;
   - each invocation has an independent 1,800 s process-CPU limit, for at most 585 solver CPU-hours;
   - the timing repetitions are separate and off.

   The approval input must be `APPROVE-` followed by the first 16 hex digits of the SHA-256 of that file at the dispatched commit:

   ```bash
   echo "APPROVE-$(sha256sum integration/benchmark/MANIFEST.json | cut -c1-16)"
   ```

   Any edit to the manifest changes the token.
2. **Validated build.** A passing "Integration v1 public validation" run of the **same commit** must exist. Its recorded build (`integration-results:runs/<validation_run>/build/attempt-1/`) is reused byte for byte.
3. **Workflow visible on the default branch.** GitHub only offers `workflow_dispatch` for workflow files that exist on the default branch. This research work does not modify `main`. The owner must therefore decide to add a copy of `.github/workflows/integration-reserved.yml` to `main`, for example as a one-file commit. When it is dispatched with `--ref integration-v1-20261124`, GitHub uses the workflow definition and code of the research branch.

## Command

```bash
gh workflow run integration-reserved.yml --repo mohamad-alaalami/fvs-stage-c \
  --ref integration-v1-20261124 \
  -f approval=APPROVE-<16 hex> \
  -f validation_run=<run id of the passing public validation>
```

## Retries

- Re-run failed jobs only. A job fails only on an infrastructure failure, so this retries exactly the infrastructure-failed jobs as a new attempt, at most twice. The rule is in `integration/PROTOCOL.md`.
- Every attempt is kept under `integration-results:runs/<run_id>/jobs/<solver>/<graph>/attempt-<n>/`.
- The report job aggregates all attempts with the fixed attempt rule.
