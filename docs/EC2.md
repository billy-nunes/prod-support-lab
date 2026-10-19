# Running the lab on a small AWS EC2 instance

Tested target: Ubuntu on a t2.micro / t3.micro (1 GB RAM, 2 vCPU, 8 GB disk). Bigger instances can use the defaults.

Working on a Linux box over SSH is closer to real production support than Docker Desktop on a laptop, so this is a good way to run it. Three things are different on 1 GB:

| Problem | What to do |
|---------|------------|
| 1 GB RAM is not enough for the default settings | Smaller data set and memory limits in `.env`, plus a 2 GB swap file |
| Ports are bound to 127.0.0.1 (on purpose) | Reach the shop from your Mac with an SSH tunnel. Do NOT open 8080 or 55432 in the security group |
| t2/t3 CPUs are "burstable" | `runaway-query` and constant load use CPU credits. Run `make down` when you finish for the day |

## 1. Check the box

```bash
free -h              # total memory
df -h /              # want at least 4 GB free
docker compose version
docker ps            # stop any old lab stacks first, they compete for the same 1 GB
```

## 2. Add swap (once)

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
free -h              # Swap: 2.0Gi
```

## 3. Get the code and configure it

```bash
sudo apt-get install -y make git
git clone https://github.com/<your-username>/prod-support-lab.git
cd prod-support-lab
cat > .env <<'EOF'
SEED_SCALE=0.05
PG_SHARED_BUFFERS=64MB
APP_MEM_LIMIT=200m
LOADGEN_RPS=2
EOF
make up
docker compose logs -f db      # wait for "ready to accept connections" after the restart, Ctrl+C
make status
```

`SEED_SCALE=0.05` gives 50k orders. The missing-index lesson still works, the numbers are just smaller. Once things are stable you can try `make nuke && make up SEED_SCALE=0.2` and watch `free -h` while it seeds. Finding the limit is a lesson too.

## 4. Open the shop from your Mac

Run this on your **Mac**, not on the instance (use the same key and host you normally SSH with):

```bash
ssh -i ~/.ssh/<your-key>.pem -L 8080:localhost:8080 ubuntu@<instance-public-dns>
```

While that session is open, http://localhost:8080/products on your Mac reaches the lab. Add `-L 3000:localhost:3000 -L 9090:localhost:9090` in Week 6 for Grafana and Prometheus.

## 5. Push from the instance (optional)

If you want to commit incident write-ups directly on the instance, give it a **deploy key** for this one repo instead of your personal GitHub key:

```bash
ssh-keygen -t ed25519 -C "ec2-prod-support-lab" -f ~/.ssh/prodlab_deploy -N ""
cat ~/.ssh/prodlab_deploy.pub
```

GitHub repo > Settings > Deploy keys > Add, paste it, tick **Allow write access**. Then:

```bash
cat >> ~/.ssh/config <<'EOF'
Host github.com
  IdentityFile ~/.ssh/prodlab_deploy
EOF
git remote set-url origin git@github.com:<your-username>/prod-support-lab.git
```

A deploy key can only touch this one repository, so a compromised instance cannot reach the rest of your GitHub account.

## Day-to-day

```bash
make up        # start of a session
make down      # end of a session (keeps the data, saves CPU credits)
```
