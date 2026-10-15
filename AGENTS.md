# Maintainer instructions

For every requested change to this repository, finish implementation and appropriate validation, publish the completed changes to GitHub, then run `.github/workflows/daily_ath_email.yml` on the updated `main` branch. Verify that the Actions validation steps and actual email-send step succeed before reporting completion. Publishing code or passing a separate validation workflow alone does not complete the task.

Scheduled reports must run Tuesday through Saturday at 07:00 Asia/Seoul for Monday through Friday market results (`0 22 * * 1-5` in UTC). Do not schedule Sunday or Monday sends. Explicit post-change verification sends requested by the maintainer are separate from that schedule.

Show the stock and ETF breakdown, computed from the actual rows, for both countries' overall counts and both countries' newly appearing counts.
