import { Link } from "react-router-dom";

import type { Service, TopologyContext } from "../api/types";
import { TierBadge } from "./Badge";

function ServiceChip({ service, affected }: { service: Service; affected: boolean }) {
  return (
    <li className={affected ? "service-chip is-affected" : "service-chip"}>
      <span className="service-chip__name">{service.name}</span>
      <span className="service-chip__id">{service.id}</span>
      {affected ? <span className="service-chip__flag">affected</span> : null}
    </li>
  );
}

export function TopologyView({ topology }: { topology: TopologyContext }) {
  if (!topology.service_found || !topology.focus_service) {
    return (
      <div className="topology topology--unmapped">
        <p className="topology__warning">
          The primary service is not in <code>config/services.yaml</code>. Ownership and
          dependency context is limited to alert labels until the catalog is updated.
        </p>
        <p className="muted">
          Affected services: {topology.affected_services.join(", ") || "unknown"}
        </p>
      </div>
    );
  }

  const affected = new Set(topology.affected_services);
  return (
    <div className="topology">
      <div className="topology__columns">
        <div className="topology__column">
          <p className="topology__label">Calls into focus · upstream</p>
          {topology.upstream.length > 0 ? (
            <ul className="service-chips">
              {topology.upstream.map((service) => (
                <ServiceChip key={service.id} service={service} affected={affected.has(service.id)} />
              ))}
            </ul>
          ) : (
            <p className="muted">No direct callers in the catalog.</p>
          )}
        </div>
        <div className="topology__focus">
          <p className="topology__label">Focus service</p>
          <div className="focus-card">
            <div className="focus-card__heading">
              <Link to={`/services?service=${topology.focus_service.id}`}>
                {topology.focus_service.name}
              </Link>
              <TierBadge tier={topology.focus_service.tier} />
            </div>
            <p className="focus-card__id">{topology.focus_service.id}</p>
            <p>{topology.focus_service.description}</p>
            <dl className="mini-facts">
              <div>
                <dt>Owner</dt>
                <dd>{topology.owner}</dd>
              </div>
              <div>
                <dt>Team</dt>
                <dd>{topology.team}</dd>
              </div>
            </dl>
          </div>
        </div>
        <div className="topology__column">
          <p className="topology__label">Focus depends on · downstream</p>
          {topology.downstream.length > 0 ? (
            <ul className="service-chips">
              {topology.downstream.map((service) => (
                <ServiceChip key={service.id} service={service} affected={affected.has(service.id)} />
              ))}
            </ul>
          ) : (
            <p className="muted">No direct dependencies in the catalog.</p>
          )}
        </div>
      </div>
      <p className="topology__disclaimer">{topology.disclaimer}</p>
    </div>
  );
}
