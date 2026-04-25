# Use BIGINT IDENTITY primary keys, not UUIDs

The API is consumed only by internal Humana associates — there is no external
exposure, federation, or cross-system ID sharing. We use
`BIGINT GENERATED ALWAYS AS IDENTITY` for every primary and foreign key.

UUIDs were considered and rejected: their usual benefits (opacity, decentralized
generation, federation safety) don't apply to an internal-only service, and they
would cost index size, join performance, and log readability. If a future
requirement introduces external consumers, the migration cost is real but
contained — re-evaluate then, not preemptively.
