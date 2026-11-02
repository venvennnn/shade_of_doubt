# Railway

`.railway/railway.ts` is the project graph: Postgres, the API, the worker, and the web app. Railway does not apply this file on git push. From the repository root, after `npm install`:

```bash
railway login
railway link
railway config plan
railway config apply
```

Set `YOUCAM_API_KEY` and `YOUCAM_UNIT_COST_PER_TASK` on the API and worker in the Railway dashboard. Those keys are `preserve()` in the graph so a later apply keeps the values you entered.
