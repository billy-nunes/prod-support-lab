# Migrations

Changes you make to the database after it is seeded go here as numbered files, for example
`001_orders_customer_id_idx.sql`. Apply one with:

```bash
docker compose exec -T db psql -U postgres -d shop -v ON_ERROR_STOP=1 < db/migrations/001_orders_customer_id_idx.sql
```

Why not edit `db/init/`? Those scripts only run on a brand-new, empty database volume.
In production you never get to re-create the database, so practise changing it in place.
