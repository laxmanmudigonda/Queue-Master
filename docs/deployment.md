# Public demo on an Always Free VM

The repository includes `compose.public.yml` for one always-on Linux VM. The
web API, worker, scheduler, PostgreSQL, Redis, and HTTPS proxy all run on the
same machine. Oracle Cloud's **Always Free** Ampere A1 VM is a possible host;
free VM capacity is not guaranteed. Oracle requires a card to verify account
identity, and its 30-day trial offers additional **paid-after-trial** services:
choose only an **Always Free eligible** A1 shape and boot volume within the
Always Free allowance. Do not select Pay As You Go or a paid shape.

1. Create an Oracle Cloud Free Tier account and an **Always Free eligible**
   Ubuntu Ampere A1 VM (for example, 1 OCPU, 6 GB RAM, 50 GB boot volume),
   with a public IPv4 address and an SSH key you control. Availability varies
   by region. Allow inbound TCP **80** and **443** in its network security
   list. Keep PostgreSQL 5432, Redis 6379, and API 8000 closed publicly.
2. SSH into the VM; install Docker Engine and the Docker Compose plugin using
   the [official Ubuntu instructions](https://docs.docker.com/engine/install/ubuntu/).
   Follow the [Linux post-installation guide](https://docs.docker.com/engine/install/linux-postinstall/)
   if you need to run Compose without `sudo`. Restrict SSH to your own IP.
3. Clone `https://github.com/laxmanmudigonda/Queue-Master.git` on the VM and
   enter the repository. Run `python3 scripts/init_env.py` **once** (skip it
   if `.env` already exists). Set restrictive permissions with `chmod 600 .env`.
4. Point a DNS name at the VM's public IPv4 address. A free testing hostname
   such as `123-45-67-89.sslip.io` resolves to IP `123.45.67.89`; replace
   those digits with your **actual** public IP. Append
   `PUBLIC_DOMAIN=123-45-67-89.sslip.io` to `.env` using your actual hostname.
   Caddy needs ports 80 and 443 to obtain and renew the HTTPS certificate.
5. Start the stack:

   ```sh
   docker compose -f compose.public.yml up -d --build --scale worker=2 --wait
   docker compose -f compose.public.yml ps
   ```

6. Visit `https://YOUR-PUBLIC-DOMAIN/`, submit a Fibonacci job, and inspect
   its completed result. `/ready` should report `{"status":"ready"}`.
   Visitors can use the public demo with no API key. The owner can use the
   Access button and their private `API_KEY` from `.env` for cancel/retry.

The public demo shares its job list and results with **everyone**. Never
submit private information. The public token permits only limited task types
and imposes a global quota of 100 submissions per UTC day. Visitors cannot
cancel or retry other jobs. An adversary can exhaust that day's shared quota;
this is a portfolio demo, not a multi-tenant production service. Back up the
PostgreSQL data volume and keep the VM updated. The web URL stays available
independently of your Windows computer and VS Code, while the VM runs.

The previously merged `render.yaml` used paid resources; this change removes
it. Do not click **Deploy Blueprint** on Render using that older commit.
