
We include three example projects that are already instrumented. 
They are readily runnable with `docker-compose`.

## Running C Benchmarks

Supported comparison tools include `klee`, `klee-pending`, `symcc`, `symsan`, and `aflplusplus`. 
The base image of `klee-pending` is available [here](https://srg.doc.ic.ac.uk/projects/pending-constraints/artifact.html), and the other images are built from dockerfiles.
For more details, see the [docker-compose file](./c_c++_programs/docker-compose.yml).

To test `bc` with ConcoLLMic, switch to the `experiments/c_c++_programs` and simply run

```bash
TIMEOUT=48h ANTHROPIC_API_KEY="your_api_key" \
docker-compose up --build \
    --scale bc-concolic=1 \
    bc-concolic
```
By default, ConcoLLMic exits after 30 min of (internal) coverage plateau. On average, this container will run for 5.5 hours at the cost of ~$65.

To run comparison tools, e.g. 5 instances of `klee` and `aflplusplus` for 48 hours, run

```bash
TIMEOUT=48h docker-compose up --build \
    --scale bc-klee=5 \
    --scale bc-aflplusplus=5 \
    bc-klee \
    bc-aflplusplus
```

## Running Multi-language Benchmarks

Similarly, see the [docker-compose file](./multi-language/docker-compose.yml) for running multi-language projects.

## Variables in Docker

1. Environment Variables
   - `PROJECT_PATH`: The path of the project.

2. Executable Scripts
   - `/bin/build.sh`: (Re-)build the project.
   - `/bin/run_target.sh`: Run the target program.
