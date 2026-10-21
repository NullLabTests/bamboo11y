# Ideas we are grateful for

Bamboo11y is an independent project. It is **not affiliated with, endorsed by, or a
copy of** BigPanda, and none of BigPanda's code, schemas, trademarks, or brand assets are
used here. The name is a pun: bamboo (what pandas eat) + **o11y** (the observability
numeronym). Public, attributable sources are credited below because good engineering is
built in the open and credit is part of the product.

## What was learned and borrowed (as ideas, with our own implementation)

### The open-integration pattern (BigPanda)

BigPanda's public documentation describes an **Open Integration Manager** concept: every
monitoring system can feed one vendor-neutral alert event, consisting of an application
identifier, a check name, a lifecycle status (`ok`, `critical`, `warning`,
`acknowledged`), and arbitrary tags — and the platform normalizes the rest.

Bamboo11y implements its own wire format in that spirit:
`POST /api/webhooks/alerts/open-integration` accepts `{app, check, status, subject,
description, timestamp, severity, tags}` and normalizes it into the same dedupe,
enrichment, correlation, and lifecycle pipeline as the Alertmanager and CloudWatch
adapters. The state mapping table is documented in [`spec.md`](spec.md). Implementation:
`backend/app/adapters/open_integration.py`.

### BigPanda's public GitHub repositories

The [`bigpandaio`](https://github.com/bigpandaio) organization has been publishing
monitoring glue since its early days. Repos that informed this project's *ideas*:

| Repository | License | What we took from it |
|---|---|---|
| [`bigpanda-rb`](https://github.com/bigpandaio/bigpanda-rb) | MIT | A client library wrapping an events API — the idea that a tiny, documented payload contract beats per-tool integrations. |
| [`puppet-bigpanda`](https://github.com/bigpandaio/puppet-bigpanda) | MIT | Infrastructure-as-code installation of event forwarding — reinforced a "the receiver should be config, not a project" mindset. |
| [`check_graphite`](https://github.com/bigpandaio/check_graphite) | MIT | Nagios-side poller used to bridge old tooling to a new incident bus — exactly the "any source in, one pipeline" problem Bamboo11y solves. |
| [`collectd-plugins`](https://github.com/bigpandaio/collectd-plugins) | none stated | AmqpGraphite forwarding glue; inspiration for keeping ingestion weekends-proof and sidecar-simple. |
| [`nagios_plugins_rabbitmq`](https://github.com/bigpandaio/nagios_plugins_rabbitmq) | Apache-2.0 | Checks for message pipelines via management APIs — informed the strict no-trust(payload) validation style of Bamboo11y's adapters. |
| [`seeds`](https://github.com/bigpandaio/seeds) | none stated | "Seed projects" — the notion that a starter repo should run end-to-end with no credentials, which motivated the local-first, mock-Slack design. |

We read these repositories for *design ideas only*. No source code or files were copied
into Bamboo11y. Their licenses apply to the original repositories, not to this one.

## What Bamboo11y does differently

- **Correlation is deterministic and explainable.** Rule-ordered grouping with stored,
  human-readable reasons — no opaque scoring, no black-box model.
- **Local-first.** SQLite, zero external services, mock Slack by default. The credits
  above describe hosted products; Bamboo11y runs on a laptop.
- **Context, not cause.** Change/deployment events are shown as temporal context only;
  UI and API copy never claim causation.
- **Idempotency front and center.** Delivery IDs + fingerprint dedupe are first-class API
  behavior, not an afterthought.

## Standing on broader shoulders

The deterministic pipeline also follows ideas from the wider open-source ecosystem it
integrates with directly: [Prometheus Alertmanager](https://github.com/prometheus/alertmanager)
(webhook payload shape), [AWS CloudWatch/SNS](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/)
(alarm state-change format), and [Pydantic](https://github.com/pydantic/pydantic) +
[FastAPI](https://github.com/fastapi/fastapi) for the strict-validation style.
