# Quiz-lite backlog

Post-MVP ideas. Nothing here is built unless the owner asks for it.

- **Automated post-deploy smoke job.** Run `scripts/smoke.sh` against the Render URL after each deploy, instead of by hand. Today the CD gate is Render's `autoDeployTrigger: checksPass` and the smoke check is manual (see `docs/plan.md`, Deploy).
