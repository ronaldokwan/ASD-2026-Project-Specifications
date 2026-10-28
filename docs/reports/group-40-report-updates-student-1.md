# group-40 report – paste-in updates (Student 1 / group)

Drop-in replacements for the Word report. Facts come from GitHub Actions run
40471342463 and `docs/evidence/student-1/release-2/cloud-deployment-run-40471342463/`.

---

## §9 Cloud Deployment Report and Review — replace the first two paragraphs and the "TODO (group)" note

The group application is deployed to AWS (ap-southeast-2) from one Terraform configuration (`infra/aws/`) and the reusable `scripts/aws/` scripts, both by hand and through GitHub Actions.

| Deployment | When / how | Result | Evidence |
|---|---|---|---|
| Scripted | 23 Oct 2026, `scripts/aws/deploy.sh`, tag `r2-202610230339` | 16 images pushed to ECR, ECS 16/16 services running, `validate-runtime.sh` passed; stack removed with `destroy.sh` | `aws/`, `cloud-review/` |
| Workflow | 27 Oct 2026, `cloud-deployment.yml` run 40471342463 on `main`, commit `1d0d0a2` | Both jobs succeeded; application live | `cloud-deployment-run-40471342463/` |

**cloud-deployment.yml run 40471342463.** The *Required integrated validation* job ran first:
- security hooks 3/3 passed
- Student 1 (149), Student 3 (58), Student 4 (36) and Student 5 (64) tests passed
- Student 2's Maven build and tests passed
- shared AI-Mode (29) and Multi-Agent (33) tests passed
- Terraform, Compose and scripts validated
- all 16 images built

Only then did *Deploy validated commit to AWS* start. It:
- assumed the GitHub OIDC role, with no stored AWS keys
- pushed the 16 images tagged with the tested commit SHA
- applied 112 Terraform resources
- ran `validate-runtime.sh` (08:26 UTC), which passed: home page and frontends :3001–:3005 HTTP 200, Student 1 and Student 3 create/update/delete verified through their databases, and AI services disabled (`AI_MODE_ENABLED`, `MCP_ENABLED`, `RAG_ENABLED`, `MULTI_AGENT_ENABLED` = `false`)

Three earlier runs on 26 Oct failed and were fixed:
1. Student 2 Dockerfile paths (run 40342920579).
2. The OIDC trust subject (run 40345701948).
3. Validation running before the new tasks passed health checks, which made the load balancer return HTTP 503 (run 40347478201). `validate-runtime.sh` now waits for each page.

The live application is at `http://asd26-g40-r2-alb-1236575834.ap-southeast-2.elb.amazonaws.com`.

**Final human release decision: approve release.** The group approves the AWS release on the evidence above:
- the integrated application and CRUD work in the cloud
- AI-Mode, MCP, RAG and Multi-Agent stay disabled by default
- `cloud-deployment.yml` deployed the tested commit only after integrated validation passed
- runtime validation and the Cloud Deployment Review both report it ready

Figures to add (screenshots):
- *Figure X. cloud-deployment.yml run 40471342463: Required integrated validation → Deploy validated commit to AWS, both succeeded.* Take this from the run's summary page.
- *Figure X+1. Deploy job log: Terraform "Apply complete! Resources: 112 added", frontend URLs and the passing runtime-validation result.* Take this from the end of step 5 of the deploy job.

## §9.1 Student 1 — replace the first sentence

Deployed with `scripts/aws/deploy.sh` on 23 Oct 2026 (tag `r2-202610230339`) and by `cloud-deployment.yml` on 27 Oct 2026 (run 40471342463, tag `1d0d0a2…`). `validate-runtime.sh` passed both times (`aws/`, `cloud-deployment-run-40471342463/`).

## §11 GitHub Commit Logs — replace the table

Commit history: https://github.com/ronaldokwan/ASD-2026-Project-Specifications/commits/main

| Student | Release 2 commits |
|---|---|
| 1 – Ronaldo Kwan | https://github.com/ronaldokwan/ASD-2026-Project-Specifications/commits/main?author=ronaldokwan |
| 2 – Jinying Li | https://github.com/ronaldokwan/ASD-2026-Project-Specifications/commits/main?author=JYL701 · https://github.com/ronaldokwan/ASD-2026-Project-Specifications/commits/main?author=XanonymXX |
| 3 – Vishvak Ananthakrishnan Rameshkumar | https://github.com/ronaldokwan/ASD-2026-Project-Specifications/commits/main?author=vishvak8 · https://github.com/ronaldokwan/ASD-2026-Project-Specifications/commits/main?author=Vish7A |
| 4 – Jonathan Czesler | https://github.com/ronaldokwan/ASD-2026-Project-Specifications/commits/main?author=Jono-Cz |
| 5 – Alexander McGuinn | https://github.com/ronaldokwan/ASD-2026-Project-Specifications/commits/main?author=AlexMcGuinn |

## §12.1 Student 1 contribution log — replace the 27 Oct row and add 28 Oct

| Date | Work |
|---|---|
| 26–27 Oct 2026 | GitHub OIDC deploy role (`infra/aws/github-oidc/`) and the `aws-production` environment; fixed three `cloud-deployment.yml` failures (Student 2 image paths, OIDC trust subject, `validate-runtime.sh` health-check wait), after which run 40471342463 deployed to AWS; multi-server check script; evidence logs |
| 28 Oct 2026 | Collected the run 40471342463 deployment evidence; integrated the group report as team leader |
