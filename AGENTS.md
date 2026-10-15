# Maintainer instructions

For every requested change to this repository, finish implementation and appropriate validation, publish the completed changes to GitHub, then run `.github/workflows/daily_ath_email.yml` on the updated `main` branch. Verify that the Actions validation steps and actual email-send step succeed before reporting completion. Publishing code or passing a separate validation workflow alone does not complete the task.

Scheduled reports must run Tuesday through Saturday at 07:00 Asia/Seoul for Monday through Friday market results (`0 22 * * 1-5` in UTC). Do not schedule Sunday or Monday sends. Explicit post-change verification sends requested by the maintainer are separate from that schedule.

Show the stock and ETF breakdown, computed from the actual rows, for both countries' overall counts and both countries' newly appearing counts.

The current readable report style uses 12.35px stock/new-row text and 13px ETF return text (about 30% larger than the earlier style), with 1px horizontal cell padding. Security names must stay on one line and display an ellipsis when they overflow; retain their full text in the HTML. Industry and index labels may wrap. Keep ticker/numeric fields on one line.

The ETF comparison shows lifetime annualized cumulative return immediately after cumulative return, sorted ascending by the unrounded lifetime rate (maximum 20 rows). Show the elapsed years used immediately after inception date. Annualize cumulative growth using actual days from valid inception date to the latest observed price date divided by 365.25; fall back to the first available trading date when inception is unavailable. Preserve the separate recent-period CAGR columns.
