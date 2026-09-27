# Hosting QueueMaster on Render

`render.yaml` provisions a public API/dashboard, a worker, a scheduler, private
PostgreSQL, and private Redis-compatible Key Value. The API runs Alembic
migrations before each deploy. This setup requires paid always-on services;
review the total cost in Render before approving deployment. Do not use the
local `.env` values on the hosted deployment.

1. Push `render.yaml` and the PostgreSQL URL normalization in `app/config.py`
   to the GitHub `main` branch. Confirm GitHub Actions passes.
2. Sign in at [Render](https://dashboard.render.com/) and connect your GitHub
   account. Select **New > Blueprint**, choose `laxmanmudigonda/Queue-Master`,
   and select `main`. Render reads the root `render.yaml` automatically.
3. Review the services and recurring charges before pressing **Deploy Blueprint**.
   Wait until the database, queue, worker, scheduler, and web service are healthy.
4. Open the URL shown on the `queuemaster-api` web service. Its `/ready`
   endpoint should respond with `{"status":"ready"}`.
5. For owner access to the interactive dashboard, copy `API_KEY` from the
   `queuemaster-api` service's environment variable settings into the
   dashboard's connection prompt. Keep this value private. Do not add it to
   the README or share it publicly.

The homepage URL is public, but the current dashboard's job views and actions
require an API key. This deployment is **not an anonymous interactive demo**.
Implement a bounded public demo mode before inviting visitors to submit jobs;
do not publish the shared administrative API key. `localhost` and your local
Docker containers are separate from the hosted deployment.
