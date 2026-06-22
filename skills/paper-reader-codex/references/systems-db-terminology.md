# Systems and Database Reading Profile

Use this profile for computer systems, storage, cloud, distributed systems, and database papers.

## Venues

Treat these as strong signals for the `systems-db` profile:

- SIGMOD
- VLDB / PVLDB
- CIDR
- TODS
- SOSP
- OSDI
- NSDI
- FAST
- ATC
- EuroSys
- ASPLOS
- SoCC
- Middleware

## What to extract

### Problem framing

- What bottleneck, correctness issue, or operational constraint is the paper attacking?
- What assumptions about hardware, cluster shape, workload, or failures are required?

### Design

- data layout, storage engine, scheduler, cache, index, replication strategy, consensus path, recovery protocol, or RPC stack
- fast path versus slow path
- write/read amplification or resource tradeoffs

### Evaluation

Always capture the actual metrics, not vague summaries. Common metrics:

- throughput
- median latency
- tail latency such as p95 or p99
- recovery time
- storage overhead
- memory footprint
- CPU utilization
- network overhead
- availability or failure recovery behavior
- cost per query or cost per transaction

### Workload and environment

- benchmark names such as YCSB, TPC-C, TPC-H, LinkBench, RocksDB db_bench
- request mix, skew, key distribution, concurrency, dataset scale
- machine shape, CPU count, memory, storage medium, NIC speed, cloud instance type
- software stack: kernel, filesystem, RDMA, database engine version

## Critique lenses

Ask these directly:

1. Does the evaluation match the deployment model claimed by the paper?
2. Are the baselines tuned fairly, or are defaults being compared to a custom system?
3. Does the paper win on average while hiding p99 regressions, recovery cost, or operator complexity?
4. Is correctness weakened through a narrower isolation or consistency model?
5. Would the claimed benefit survive a different workload skew, storage medium, or cluster size?

## Concept note categories

Prefer concept notes for:

- protocols: Raft, Paxos, two-phase commit, MVCC
- storage structures: LSM tree, B-tree, Bw-tree, memtable
- scheduling or execution models: vectorized execution, pipelining, work stealing
- deployment primitives: disaggregation, SmartNIC offload, RDMA verbs
- benchmark suites and fault models
