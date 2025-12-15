

## Key points:

- No DB access here.

- It only calls another contract (Governance) and shapes the DTO.

- `log_expense` remains untouched and policy-blind.

### So your canonical usage becomes:

```python
preview = finance_v2.preview_expense(
    fund_id=fund_id,
    project_id=project_id,
    fund_archetype_key="grant_reimbursement",
    project_type_key="stand_down",
    amount_cents=amount_cents,
    period_label="2026-03",
    current_spent_cents=current_spent_cents,
)

if not preview["ok"]:
    # block or go to override flow
else:
    expense = finance_v2.log_expense(
        fund_id=fund_id,
        project_id=project_id,
        occurred_on=occurred_on,
        vendor=vendor,
        amount_cents=amount_cents,
        category=category,
        # etc...
    )
```
