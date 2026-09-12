# Use BIGINT IDENTITY primary keys, not UUIDs

The API is consumed only by internal Humana associates — there is no external exposure, federation, or cross-system ID sharing. We use `BIGINT GENERATED ALWAYS AS IDENTITY` for every primary and foreign key.

UUIDs were considered and rejected: their usual benefits (opacity, decentralized generation, federation safety) don't apply to an internal-only service, and they would cost index size, join performance, and log readability. If a future requirement introduces external consumers, the migration cost is real but contained — re-evaluate then, not preemptively.

Revisit when: "a future requirement introduces external consumers" — re-evaluate then, not preemptively. The premise this rests on, that the deployment is reachable from the intranet and nowhere else, is decided in [ADR 0042](0042-no-authentication-on-an-intranet-only-deployment.md), whose own triggers fire first.
