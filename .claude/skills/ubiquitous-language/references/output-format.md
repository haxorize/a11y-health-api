# Output Format

Use this structure when writing `UBIQUITOUS_LANGUAGE.md`.

```markdown
# Ubiquitous Language

## <Group Name>

| Term        | Definition                                              | Aliases to avoid      |
| ----------- | ------------------------------------------------------- | --------------------- |
| **Order**   | A customer's request to purchase one or more items      | Purchase, transaction |
| **Invoice** | A request for payment sent to a customer after delivery | Bill, payment request |

## <Another Group>

| Term         | Definition                                  | Aliases to avoid       |
| ------------ | ------------------------------------------- | ---------------------- |
| **Customer** | A person or organization that places orders | Client, buyer, account |

## Relationships

- An **Invoice** belongs to exactly one **Customer**
- An **Order** produces one or more **Invoices**

## Example dialogue

> **Builder:** "When a **Customer** places an **Order**, do we create the **Invoice** immediately?"
>
> **Specifier:** "No — an **Invoice** is only generated once a **Fulfillment** is confirmed. A single **Order** can produce multiple **Invoices** if items ship in separate **Shipments**."
>
> **Builder:** "So if a **Shipment** is cancelled before dispatch, no **Invoice** exists for it?"
>
> **Specifier:** "Exactly. The **Invoice** lifecycle is tied to the **Fulfillment**, not the **Order**."

## Flagged ambiguities

- "account" was used to mean both **Customer** and **User** — these are distinct concepts: a **Customer** places orders, while a **User** is an authentication identity that may or may not represent a **Customer**.
```

## Notes

- Group terms into multiple tables when natural clusters emerge. One table is fine if terms belong to a single cohesive domain.
- Use **bold** for term names in Relationships and Flagged ambiguities sections.
- The example dialogue should use **Builder** and **Specifier** as speakers.
- Keep the dialogue to 3-5 exchanges that clarify boundaries between related concepts.
