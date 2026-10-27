# Module 0 — How the database works

This is the local Postgres we created for Excon. It is **not** in the cloud. It runs in Docker on your machine.

**Short answer:** closing a terminal does **not** wipe the database. Data lives in a Docker **volume** on disk. It only disappears if you delete that volume (or uninstall Docker / wipe Docker data).

---

## 1. What we actually created

We did **not** install Postgres as a Windows program (no installer, no Service in Windows).

We defined a container in [docker-compose.yml](../docker-compose.yml):

- Image: official `postgres:16-alpine`
- First boot creates user `excon`, password `excon`, database `excon`
- Files for that database are stored in a named volume: `excon_pgdata`

Think of three layers:

```text
  Terminal / Cursor
        │  you type: docker compose up
        ▼
  Docker containers     (the running process — can stop)
        │  db container writes files into
        ▼
  Docker volume         (the actual data on disk — stays)
  name: excon_pgdata
  (on your PC, managed by Docker Desktop)
```

- **Container** = the Postgres process. Stop it and nothing is listening on port 5432.
- **Volume** = the data files. Stop the container and the files are still there. Start again and Postgres finds the same data.

---

## 2. How it was initialized (first start only)

Postgres has a rule: **only initialize if the data directory is empty**.

On the **first** `docker compose up` with a new volume:

1. Docker creates volume `excon_pgdata` (empty).
2. Docker starts the `db` container and mounts that volume at `/var/lib/postgresql/data` inside the container.
3. Postgres sees an empty folder, so it runs first-time setup:
   - create the `excon` role (user) from `POSTGRES_USER`
   - set its password from `POSTGRES_PASSWORD`
   - create database `excon` from `POSTGRES_DB`
4. After that, those env vars are **ignored** for user/db creation. Later starts just open the existing files.

We later ran `docker compose down -v` once to drop the old copied credentials and start this `excon` database clean. That **did** wipe data, because `-v` deletes the volume. A normal stop does not.

The API then connects with:

```text
postgresql+psycopg://excon:excon@db:5432/excon     (inside Docker)
postgresql+psycopg://excon:excon@localhost:5432/excon   (from your PC)
```

There are still **no seller/research tables**. Only Postgres internals plus Alembic’s bookkeeping after the API starts.

---

## 3. What happens in everyday situations

| You do this | Containers | Data in the volume |
|---|---|---|
| Close the terminal / close Cursor | **Still running** if you started with `docker compose up -d` (detached). Docker Desktop keeps them. | Kept |
| Close the terminal while `docker compose up` is in the **foreground** (no `-d`) | That command often **stops** the containers (like Ctrl+C). | **Kept** |
| Restart Cursor | Does not stop Docker | Kept |
| `docker compose stop` or `docker compose down` | Containers stop / are removed | **Kept** (`down` without `-v` does not delete the volume) |
| Reboot Windows | Containers stop unless Docker is set to restart them. We did **not** set `restart: unless-stopped`, so after reboot they are usually stopped until you `docker compose up` again. | **Kept** |
| Docker Desktop is quit | Everything in Docker stops | **Kept** (volume is on disk) |
| `docker compose down -v` | Containers **and** the volume are deleted | **Gone** |
| Uninstall Docker Desktop / “Wipe data” in Docker | | **Gone** |

Closing the terminal is safe for data. The dangerous command is **`docker compose down -v`** (`-v` = volumes).

---

## 4. How to see that it is still there

Containers running?

```bash
docker compose ps
```

Volume still on disk?

```bash
docker volume ls
```

You should see a volume whose name includes `excon_pgdata` (Docker prefixes the project folder name, so it often shows as `excon_excon_pgdata`).

API can see Postgres?

```text
GET http://localhost:8000/health/ready
→ {"status":"ok","database":"ok"}
```

---

## 5. How to start, stop, and wipe (on purpose)

Start (creates the volume the first time; reuses it after that):

```bash
docker compose up --build -d
```

`-d` = detached: the process keeps running after you close the terminal.

Stop containers, **keep** data:

```bash
docker compose down
```

Start again later — same database, same rows:

```bash
docker compose up -d
```

Delete the database **on purpose** (empty start):

```bash
docker compose down -v
docker compose up --build -d
```

Use `-v` only when you want a clean slate.

---

## 6. Where the files live

You will **not** see a `data/` folder of `.sql` files in `c:\Excon`. Docker stores volumes in Docker Desktop’s disk (on Windows that is inside the Docker VM / WSL).

That is why:

- Deleting the `c:\Excon` project folder does **not** automatically delete the volume.
- `docker compose down -v` **does** delete it, even if the project folder is still there.

---

## 7. What this is *not*

- Not a managed cloud database (RDS, Azure, etc.).
- Not installed as a Windows service.
- Not backed up yet. If the volume is deleted, local data is gone. Backups come later when we care about real user data.
- Not populated with product data yet. Module 0 only proved we can connect.
