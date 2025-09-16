#!/bin/bash

TESTER_NAME=$1
TIMEOUT=$2

hostname=`hostname | cut -c 1-4`

if [ $# -lt 1 ]; then
    echo "Usage: $0 <TESTER_NAME> [timeout_seconds]"
    echo "TESTER_NAME must be one of ['symcc', 'symsan', 'aflplusplus', 'klee', 'klee-pending', 'concolic']"
    exit 1
fi

if [ $# -eq 2 ]; then
    TIMEOUT_SECONDS=$2
    echo "Using specified timeout of $TIMEOUT_SECONDS for testing bc with $TESTER_NAME."
else
    TIMEOUT_SECONDS=60
    echo "Using default timeout of 60 seconds for testing bc with $TESTER_NAME."
fi

# Set default paths

current_time=$(date +%m%d%H%M)
export SHARED_DIR="/shared/${TESTER_NAME}-${current_time}-${hostname}"

export INPUT="${SHARED_DIR}/input"
export OUTPUT="${SHARED_DIR}/output"
export SYMCC_FAIL_DIR="${SHARED_DIR}/symcc-fail"
export SYMSAN_FAIL_DIR="${SHARED_DIR}/symsan-fail"

export GCOV_ROOT="/bc-gcov"
export KLEE_ROOT="/bc-klee"
export SYMCC_ROOT="/bc-symcc"
export SYMSAN_ROOT="/bc-symsan"
export AFLPLUSPLUS_ROOT="/bc-aflplusplus"
export INSTR_ROOT="/bc-instr"
export BIN="bc/bc"

export TESTER_EXECUTE_ARGS=""    # no arguments and stdin
export GCOVE_EXECUTE_ARGS="<"
export KLEE_SYM_ARGS="--sym-arg 2 --sym-stdin 20"

mkdir -p $INPUT

if [ "$TESTER_NAME" != "concolic" ]; then
    cp /seeds/* $INPUT/
else
    cp /seed_execs/* $INPUT/
fi

cp /run.sh ${SHARED_DIR}/run.sh

# echo execution command and start time
echo "Executing command: $0 $@" > ${SHARED_DIR}/execution_command.log
echo "Start time: $(date)" >> ${SHARED_DIR}/execution_command.log

setup_concolic_environment() {
    echo "Setting up Concolic environment"
    pushd /concolic-agent
    git fetch origin
    git reset --hard origin/main    # pull the latest version
    pip install -r requirements.txt
    pip install -r requirements-dev.txt
    git_version=$(git rev-parse HEAD)
    echo "git version: $git_version" >> ${SHARED_DIR}/execution_command.log
    popd
}

# ------------------ Start Tester ------------------
case $TESTER_NAME in
  "symcc")
    echo "Running with SymCC"
    echo "/symcc_build/pure_concolic_execution.sh -i $INPUT -o $OUTPUT -f $SYMCC_FAIL_DIR ${SYMCC_ROOT}/${BIN} ${TESTER_EXECUTE_ARGS}"  >> ${SHARED_DIR}/execution_command.log
    timeout -k 10 $TIMEOUT_SECONDS /bin/bash -c \
        "/symcc_build/pure_concolic_execution.sh -i $INPUT -o $OUTPUT -f $SYMCC_FAIL_DIR ${SYMCC_ROOT}/${BIN} ${TESTER_EXECUTE_ARGS}" \
        > ${SHARED_DIR}/symcc.log 2>&1 &
    wait
    export QUEUE_DIR="$OUTPUT"
    ;;
  "aflplusplus")
    echo "Running with AFL++"
    echo "afl-fuzz -i $INPUT -o $OUTPUT ${AFLPLUSPLUS_ROOT}/${BIN} ${TESTER_EXECUTE_ARGS}"  >> ${SHARED_DIR}/execution_command.log
    timeout -k 10 $TIMEOUT_SECONDS /bin/bash -c \
        "afl-fuzz -i $INPUT -o $OUTPUT ${AFLPLUSPLUS_ROOT}/${BIN} ${TESTER_EXECUTE_ARGS}" \
        > ${SHARED_DIR}/aflplusplus.log 2>&1 &
    wait
    chown -R $USER:$USER $OUTPUT
    export QUEUE_DIR="$OUTPUT/default/queue"
    ;;
  "symsan")
    echo "Running with SymSan"
    echo "/workdir/symsan_pure_concolic_execution.sh -i $INPUT -o $OUTPUT -f $SYMSAN_FAIL_DIR ${SYMSAN_ROOT}/${BIN} ${TESTER_EXECUTE_ARGS}"  >> ${SHARED_DIR}/execution_command.log
    timeout -k 10 $TIMEOUT_SECONDS /bin/bash -c \
        "/workdir/symsan_pure_concolic_execution.sh -i $INPUT -o $OUTPUT -f $SYMSAN_FAIL_DIR ${SYMSAN_ROOT}/${BIN} ${TESTER_EXECUTE_ARGS}" \
        > ${SHARED_DIR}/symsan.log 2>&1 &
    wait
    export QUEUE_DIR="$OUTPUT"
    ;;
  "klee" | "klee-pending")
    echo "Running with KLEE"
    echo "klee --max-memory=8000 --seed-file=${INPUT}/bc.ktest --only-output-states-covering-new --simplify-sym-indices --disable-inlining --switch-type=simple --external-calls=all --libc=uclibc --posix-runtime --output-dir=${OUTPUT}/klee-out ${KLEE_ROOT}/${BIN}.bc ${KLEE_SYM_ARGS}"  >> ${SHARED_DIR}/execution_command.log
    
    ulimit -s unlimited
    mkdir -p $OUTPUT

    timeout -k 10 $TIMEOUT_SECONDS /bin/bash -c \
        "klee --max-memory=8000 --seed-file=${INPUT}/bc.ktest --only-output-states-covering-new --simplify-sym-indices --disable-inlining --switch-type=simple --external-calls=all --libc=uclibc --posix-runtime --output-dir=${OUTPUT}/klee-out ${KLEE_ROOT}/${BIN}.bc ${KLEE_SYM_ARGS}" \
        > ${SHARED_DIR}/klee.log 2>&1 &
    
    wait
    
    export QUEUE_DIR="$OUTPUT/klee-out"
    ;;
  "concolic")
    echo "Running with Concolic"
    echo "python3 ACE.py run --project_dir $INSTR_ROOT --execution ${INPUT}/bc.py --timeout 10 --out $OUTPUT --plateau_slot 30"  >> ${SHARED_DIR}/execution_command.log

    # call the wrapped function to pull the latest version of ConcoLLMic
    setup_concolic_environment

    cd /concolic-agent
    timeout -k 10 $TIMEOUT_SECONDS /bin/bash -c \
        "python3 ACE.py run --project_dir $INSTR_ROOT --execution ${INPUT}/bc.py --timeout 10 --out $OUTPUT --plateau_slot 30" \
        > /dev/null 2>&1 &
    wait
    export QUEUE_DIR="$OUTPUT"
    ;;
esac


if [ $? -eq 124 ]; then
    echo "Testing timed out after $TIMEOUT_SECONDS seconds."
else
    echo "Testing completed. Starting replay with gcovr-instrumented binary."
fi


# ------------------ Coverage Collection ------------------

# clean up the coverage data
cd $GCOV_ROOT
gcovr -r . -s -d > /dev/null 2>&1

covfile="${SHARED_DIR}/coverage_summary.csv"

# collect coverage
if [ "$TESTER_NAME" != "concolic" ]; then
    echo "Time,l_per,l_abs,b_per,b_abs,covered_times_of_line" > $covfile

    # initialize the last coverage collection time
    last_cov_time=0

    # get all seeds and sort by time
    # 1. define test file pattern based on tester name
    case "$TESTER_NAME" in
      "klee" | "klee-pending")
        klee-stats --print-all ${OUTPUT}/klee-out > ${OUTPUT}/klee-stats.out
        TEST_FILES="*.ktest" ;;
      *)
        TEST_FILES="*" ;;
    esac

    # 2. get input seeds
    mapfile -t input_seeds < <(cd "$INPUT" && find . -maxdepth 1 -type f -name "$TEST_FILES" -not -name '.*' -printf '%T@ %p\n' | sort -n | cut -d' ' -f2- | sed "s|^./|$INPUT/|" )

    # 3. get queue seeds
    mapfile -t queue_seeds < <(cd "$QUEUE_DIR" && find . -maxdepth 1 -type f -name "$TEST_FILES" -not -name '.*' -printf '%T@ %p\n' | sort -n | cut -d' ' -f2- | sed "s|^./|$QUEUE_DIR/|" )

    # 4. combine both arrays
    seeds=("${input_seeds[@]}" "${queue_seeds[@]}")

    total_seeds_count=${#seeds[@]}
    input_seeds_count=${#input_seeds[@]}
    current_seed_index=0

    time=0

    # process seeds in batch
    for seed in "${seeds[@]}"; do
        time=$(stat -c %Y "$seed")

        # show progress
        current_seed_index=$((current_seed_index + 1))
        progress=$((current_seed_index * 100 / total_seeds_count))
        echo "Processing seed $current_seed_index of $total_seeds_count ($progress% done)"


        # run seed based on tester name
        case "$TESTER_NAME" in
          "klee" | "klee-pending")
            klee-replay ${GCOV_ROOT}/${BIN} $seed ;;
          *) 
            timeout 1s bash -c "${GCOV_ROOT}/${BIN} ${GCOVE_EXECUTE_ARGS} $seed > /dev/null 2>&1" ;;
        esac
        
        # Always collect coverage for input seeds, use time interval for queue seeds
        if [ $current_seed_index -le $input_seeds_count ] || [ $((time - last_cov_time)) -gt 2 ] || [ $last_cov_time -eq 0 ]; then

            # Run gcovr capture and check its output
            cov_data=$(bash /coverage.sh)

            echo "$time,$cov_data" >> $covfile
            
            # update the last execution time
            last_cov_time=$time
        fi
    done

    # final processing
    cov_data=$(bash /coverage.sh)
    echo "$time,$cov_data" >> $covfile

else
    cd /concolic-agent
    python3 ACE.py replay $QUEUE_DIR $GCOV_ROOT $covfile --cov_script /coverage.sh --timeout 10 > ${SHARED_DIR}/replay.log 2>&1

    python3 ACE.py run_data $QUEUE_DIR > ${SHARED_DIR}/run_data.log
fi

# Generate and save the final .gcov files
cd $GCOV_ROOT

SRC_FILES=$(find . -type f \( -name "*.c" -o -name "*.cpp" -o -name "*.cc" -o -name "*.cxx" -o -name "*.h" -o -name "*.hpp" -o -name "*.hxx" \))

for src in $SRC_FILES; do
    echo "Checking coverage for $src"
    # get the dir of the src file and the basename
    src_dir=$(dirname "$src")
    basename=$(basename "$src")
    cd "$src_dir"

    output=$(gcov -r -b -o . "$basename" 2>&1)

    echo "$output"
    
    # check if the file has coverage
    if echo "$output" | grep "Lines executed:0.00%"; then
        echo "No coverage, skipping: $src"
        rm "$basename.gcov"
    fi
    
    cd $GCOV_ROOT
done

mkdir -p "$OUTPUT/gcov"
find . -name "*.gcov" -type f -exec cp --parents {} "$OUTPUT/gcov/" \;

echo "Coverage collection completed."