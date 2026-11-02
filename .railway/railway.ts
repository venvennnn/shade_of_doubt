import { defineRailway, github, group, postgres, preserve, project, service } from "railway/iac";

const repository = "venvennnn/shade_of_doubt";

export default defineRailway(() => {
  const db = postgres("postgres");

  const api = service("api", {
    source: github(repository, { rootDirectory: "backend" }),
    start: '/bin/sh -c "./docker-entrypoint.sh uvicorn app.main:app --host 0.0.0.0 --port $PORT"',
    healthcheck: "/health",
    healthcheckTimeout: 300,
    env: {
      DATABASE_URL: db.env.DATABASE_URL,
      ENVIRONMENT: "production",
      STORAGE_BACKEND: "database",
      FRONTEND_ORIGIN: "https://${{web.RAILWAY_PUBLIC_DOMAIN}}",
      YOUCAM_API_KEY: preserve(),
      YOUCAM_UNIT_COST_PER_TASK: preserve(),
      YOUCAM_WEBHOOK_SECRET: preserve(),
      OPERATOR_USER_IDS: preserve(),
    },
  });

  const worker = service("worker", {
    source: github(repository, { rootDirectory: "backend" }),
    start: '/bin/sh -c "./docker-entrypoint.sh python -m app.worker"',
    healthcheck: "/health",
    healthcheckTimeout: 300,
    env: {
      DATABASE_URL: db.env.DATABASE_URL,
      ENVIRONMENT: "production",
      STORAGE_BACKEND: "database",
      YOUCAM_API_KEY: preserve(),
      YOUCAM_UNIT_COST_PER_TASK: preserve(),
      YOUCAM_WEBHOOK_SECRET: preserve(),
    },
  });

  const web = service("web", {
    source: github(repository, { rootDirectory: "frontend" }),
    start: '/bin/sh -c "HOSTNAME=0.0.0.0 npm start -- --hostname 0.0.0.0 --port $PORT"',
    healthcheck: "/",
    healthcheckTimeout: 300,
    env: {
      NEXT_PUBLIC_API_URL: "https://${{api.RAILWAY_PUBLIC_DOMAIN}}",
    },
  });

  return project("shade-of-doubt", {
    resources: [group("Shade of Doubt", [db, api, worker, web])],
  });
});
