# Call reports

Every guarded tool call returns a record of what the gateway did. Structured
form sits in the result `_meta` under the `aisafedb` key; a one-line summary is
also appended as a text block:

```text
aisafedb: dropped columns credit_card; hashed in query email; guard call=allow; guard result=allow
```

`executed_sql` holds the statement sent downstream with the session `data_key`
replaced by `__DATA_KEY__`, so reports are safe to log. The report is assembled
outside the guard and never enters the guard prompt.

See [Reporting API](../reference/reporting.md) for the Pydantic model.
