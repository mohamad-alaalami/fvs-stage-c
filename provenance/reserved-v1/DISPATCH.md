# Reserved benchmark (integration v1): dispatch record

- **Dispatched:** 2026-11-25T16:38:59Z by the operator on explicit owner approval (see `PRE-DISPATCH.md`).
- **Run:** [45656199418](https://github.com/mohamad-alaalami/fvs-stage-c/actions/runs/45656199418). The workflow is `integration-reserved.yml`, event `workflow_dispatch`, ref `integration-v1-20261124`, head SHA `d65bb5519edcc9f8acf8dc6bb2805fe20472d04e`.
- **Inputs:** `approval=APPROVE-32c64732c4db4dc8`, recomputed from the committed manifest immediately before dispatch, and `validation_run=45493670014`.
- **Checked immediately before dispatch:**
  - the research branch still pointed to the experiment commit;
  - no workflow run was active;
  - the reserved workflow had no previous runs.
- **Records:** `runs/45656199418/` on this branch: `schedule/attempt-<n>/`, `jobs/<solver>/<graph>/attempt-<n>/` and `report/attempt-<n>/`.
- **Retries:** only the frozen rule (infrastructure failures only; "Re-run failed jobs" re-runs whole three-policy jobs; at most two retries). Any retry will be logged in a new file in this folder.
