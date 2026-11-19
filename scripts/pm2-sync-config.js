#!/usr/bin/env node
/** Apply invoiceAudit.* from ecosystem.config.json to app args/env (keep one edit point). */
const fs = require("fs");
const path = require("path");

const root = path.join(__dirname, "..");
const cfgPath = path.join(root, "ecosystem.config.json");
const cfg = JSON.parse(fs.readFileSync(cfgPath, "utf8"));
const m = cfg.invoiceAudit;
if (!m) {
  console.error("ecosystem.config.json: missing invoiceAudit section");
  process.exit(1);
}

const api = cfg.apps.find((a) => a.name === "invoice-audit-api");
const web = cfg.apps.find((a) => a.name === "invoice-audit-web");
if (!api || !web) {
  console.error("ecosystem.config.json: missing invoice-audit-api or invoice-audit-web app");
  process.exit(1);
}

api.args = `-m uvicorn app.main:app --host ${m.apiHost} --port ${m.apiPort}`;
if (!web.env) web.env = {};
web.env.API_URL = m.apiUrl;
web.args = `run start -- -H ${m.webHost} -p ${m.webPort}`;

fs.writeFileSync(cfgPath, JSON.stringify(cfg, null, 2) + "\n");
console.log(`PM2 config: API ${m.apiHost}:${m.apiPort}  web :${m.webPort}  API_URL=${m.apiUrl}`);