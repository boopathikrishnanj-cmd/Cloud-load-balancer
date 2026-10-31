# Cloud Load Balancing Demonstrator
**U23CS702 Cloud Computing Virtualization | Non-written Test II | Reg. No. 301 | Unit III, CO3, Bloom L4**

## 1. Problem and objectives
A single cloud server becomes a bottleneck and a single point of failure. A load balancer spreads incoming requests over many servers.
Objectives: (1) implement a load balancer in front of 4 real backend servers, (2) compare 5 balancing algorithms, (3) show health checks and automatic failover, (4) show request distribution on a live dashboard.

## 2. Design
```
Clients (burst generator, 20 simulated client IPs)
        |
Load Balancer :8080  (algorithm + health checker + failover + dashboard)
   |        |        |        |
:9001    :9002    :9003    :9004      (backend servers, latency 50/100/200/400 ms, weights 5/3/2/1)
```
| Algorithm | Idea | Best for |
|---|---|---|
| Round Robin | Servers in turn | Equal servers |
| Weighted Round Robin | Share proportional to weight (smooth WRR) | Unequal capacity |
| Least Connections | Server with fewest active requests | Varying request time |
| IP Hash | hash(client IP) picks server | Session stickiness |
| Random | Random healthy server | Simple, stateless |

Health check: LB calls `/health` on each backend every 2 s. A failed forward also marks the server down and the request is retried on another server (failover).

## 3. How to run
1. Install Python 3.8+ (no other packages needed).
2. `python load_balancer.py`
3. Open `http://localhost:8080`

For the "AWS/Azure" option: copy the file to a VM (EC2/Azure VM), open port 8080 in the security group, run the same command and browse to `http://<public-ip>:8080`.

## 4. Demo script (for the live demonstration)
1. Algorithm = Round Robin, click **Send 200 requests**: all 4 servers get 25%.
2. Switch to **Weighted Round Robin**, Reset, send 200: about 45/27/18/9%.
3. Switch to **Least Connections**, Reset, send 200: slow Server-4 gets the fewest.
4. Click **Simulate crash** on Server-1, send 200: Server-1 shows DOWN, traffic is shared by the rest, 0 dropped.
5. Click **Recover server**: it turns healthy within 2 s and receives traffic again.

## 5. Sample results (100 requests, measured)
| Algorithm | S1 | S2 | S3 | S4 |
|---|---|---|---|---|
| Round Robin | 25 | 25 | 25 | 25 |
| Weighted RR | 46 | 27 | 18 | 9 |
| Least Connections | 50 | 25 | 15 | 10 |
| IP Hash | 31 | 19 | 20 | 30 |
| Random | 30 | 19 | 27 | 24 |
| Round Robin, Server-1 crashed (60 req) | 0 | 21 | 20 | 19 |

Analysis: Round Robin ignores capacity, so slow Server-4 is overloaded. Weighted RR and Least Connections match traffic to capacity. IP Hash gives sticky routing but uneven spread. On failure, no request was dropped.

## 6. Likely viva questions
- What is load balancing and why is it needed? (scalability, availability, performance)
- Layer 4 vs Layer 7 load balancer? (this project works at Layer 7 / HTTP)
- Difference between Round Robin and Least Connections?
- Why use health checks? What is failover?
- Which real services do this? (AWS ELB/ALB, Azure Load Balancer, GCP Cloud Load Balancing)
- Limitation: the LB itself is a single point of failure; real clouds run it redundantly.
