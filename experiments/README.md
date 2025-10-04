# Reproducing Experiments

This directory contains Docker-based setups for reproducing the evaluation results. All benchmarks are pre-instrumented and ready to run with `docker-compose`.

## Benchmark Categories

- **`c_c++_programs/`** — C/C++ benchmarks (see [c_c++_programs/docker-compose.yml](./c_c++_programs/docker-compose.yml))
- **`multi-language/`** — Multi-language systems (see [multi-language/docker-compose.yml](./multi-language/docker-compose.yml))

---

## Running ConcoLLMic

Navigate to the benchmark directory and run (using `bc` from `c_c++_programs/` as an example):

```bash
cd c_c++_programs

TIMEOUT=48h ANTHROPIC_API_KEY="your_api_key" \
docker-compose up --build \
    --scale bc-concolic=1 \
    bc-concolic
```


**Note**: `48h` here is upper bound of the runtime. By default, ConcoLLMic automatically terminates after 30 minutes of coverage plateau, and it typically runs for ~4.6 hours on `bc`.

---

## Running Comparison Tools

### Available Comparison Tools

Supported comparison tools (availability varies by benchmark):
- `<benchmark>-klee` — KLEE symbolic executor
- `<benchmark>-klee-pending` — KLEE with pending constraints optimization
- `<benchmark>-symcc` — SymCC compiler-based symbolic execution
- `<benchmark>-symsan` — SymSan sanitizer-based symbolic execution
- `<benchmark>-aflplusplus` — AFL++ fuzzer

**Note**: The base image for `klee-pending` needs to be prepared separately from [here](https://srg.doc.ic.ac.uk/projects/pending-constraints/artifact.html). Other tools are built from Dockerfiles we provide.

### Example: Running All Tools on `bc`

Run 5 parallel instances of all comparison tools for 48 hours:

```bash
cd c_c++_programs

TIMEOUT=48h docker-compose up --build \
    --scale bc-klee=5 --scale bc-klee-pending=5 \
    --scale bc-symcc=5 --scale bc-symsan=5 \
    --scale bc-aflplusplus=5 \
    bc-klee bc-klee-pending bc-symcc bc-symsan bc-aflplusplus
```


---

## Cleanup

Stop and remove all containers:
```bash
docker-compose down
```

---

## File Organization

Each benchmark directory contains:
- Pre-instrumented code packaged as `<benchmark>-instr.tar.gz`
- Dockerfiles for different tools
- Seed inputs in `seeds/` (for AFL++, SymCC, SymSan) or `seeds_klee/` (for KLEE, KLEE-Pending)
- Test harnesses in `seed_execs/` (for ConcoLLMic)

Results (test cases, logs, coverage data) are stored in subdirectories after execution, e.g., `bc/results`

