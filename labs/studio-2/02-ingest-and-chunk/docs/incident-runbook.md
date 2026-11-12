# Warehouse Systems Incident Runbook

Fictional document for a course lab. It describes how the Harbor & Pine operations team responds when warehouse
systems fail.

## Severity levels

A Sev 1 incident stops orders from shipping: the warehouse management system is down, or label printing fails for
every carrier. A Sev 2 incident slows shipping but has a workaround, such as one carrier's labels failing. A Sev 3
incident is cosmetic or affects internal reports only.

## First fifteen minutes

Open an incident channel named after the date and the system, for example inc-2026-11-03-wms. Name an incident lead
and a scribe. The lead decides; the scribe writes down every action with a timestamp. Post a first status update
within fifteen minutes even if you know nothing yet.

## Label printer failures

Most label failures come from the print server losing its connection to the carrier API. Restart the print-bridge
service first. If labels still fail after a restart, switch the affected carrier to manual label mode, which lets
packers print labels from the carrier's own website. Manual mode is slower, so tell the shift lead to expect fewer
shipments per hour.

## Inventory sync errors

If the store systems show stock that the warehouse does not have, pause the nightly sync job before it runs again.
A bad sync copies the error to all three stores. Then compare yesterday's export with the warehouse count and fix
the rows by hand. Never delete the sync log; finance uses it for month-end reconciliation.

## After the incident

Write a short review within five working days: what happened, how it was detected, what was done, and what will
change. Reviews are blameless. Link the review in the incident channel and archive the channel.
