#!/bin/bash

TESTER_NAME=$1
TIMEOUT=$2

hostname=`hostname | cut -c 1-4`

if [ $# -lt 1 ]; then
    echo "Usage: $0 <TESTER_NAME> [timeout_seconds]"
    echo "TESTER_NAME must be 'concolic'"
    exit 1
fi

if [ $# -eq 2 ]; then
    TIMEOUT_SECONDS=$2
    echo "Using specified timeout of $TIMEOUT_SECONDS for testing ultrajson with $TESTER_NAME."
else
    TIMEOUT_SECONDS=60
    echo "Using default timeout of 60 seconds for testing ultrajson with $TESTER_NAME."
fi

# Set default paths

current_time=$(date +%m%d%H%M)
export SHARED_DIR="/shared/${TESTER_NAME}-${current_time}-${hostname}"

export INPUT="${SHARED_DIR}/input"
export OUTPUT="${SHARED_DIR}/output"

export COV_ROOT="/ultrajson_cov"
export INSTR_ROOT="/ultrajson_instr"
export ASAN_ROOT="/ultrajson_asan"

mkdir -p $INPUT

cp /seed_execs/* $INPUT/

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
export PYTHONPATH=${INSTR_ROOT}

echo "Running with Concolic"
echo "python3 ACE.py run --project_dir $INSTR_ROOT --execution ${INPUT}/run.py --timeout 10 --out $OUTPUT --plateau_slot 30"  >> ${SHARED_DIR}/execution_command.log

# call the wrapped function to pull the latest version of ConcoLLMic
setup_concolic_environment

cd /concolic-agent
timeout -k 10 $TIMEOUT_SECONDS /bin/bash -c \
    "python3 ACE.py run --project_dir $INSTR_ROOT --execution ${INPUT}/run.py --timeout 10 --out $OUTPUT --plateau_slot 30" \
    > /dev/null 2>&1 &
wait
export QUEUE_DIR="$OUTPUT"


if [ $? -eq 124 ]; then
    echo "Testing timed out after $TIMEOUT_SECONDS seconds."
else
    echo "Testing completed. Starting replay with gcovr-instrumented binary."
fi


# ------------------ Replay for bug detection ------------------

export ASAN_OPTIONS='abort_on_error=1:symbolize=0:detect_leaks=0:detect_stack_use_after_return=1:detect_container_overflow=0:poison_array_cookie=0:malloc_fill_byte=0:max_malloc_fill_size=16777216'
export UBSAN_OPTIONS='print_stacktrace=1:halt_on_error=1:abort_on_error=1:malloc_context_size=0:allocator_may_return_null=1:symbolize=1:handle_segv=0:handle_sigbus=0:handle_abort=0:handle_sigfpe=0:handle_sigill=0'
export LD_PRELOAD=/usr/lib/llvm-14/lib/clang/14.0.0/lib/linux/libclang_rt.asan-x86_64.so
unset PYTHONPATH

export PYTHONPATH=${ASAN_ROOT}

covfile="${SHARED_DIR}/coverage_summary.csv"

python3 ACE.py replay $QUEUE_DIR $ASAN_ROOT $covfile --timeout 10 > ${SHARED_DIR}/replay.log 2>&1

python3 ACE.py run_data $QUEUE_DIR > ${SHARED_DIR}/run_data.log

echo "Replaying completed."


# # ------------------ Coverage Collection ------------------

# # clean up the coverage data
# unset PYTHONPATH
# export PYTHONPATH=${COV_ROOT}
# cd $COV_ROOT
# gcovr -r . -s -d > /dev/null 2>&1

# covfile="${SHARED_DIR}/coverage_summary.csv"

# cd /concolic-agent
# python3 ACE.py replay $QUEUE_DIR $COV_ROOT $covfile --cov_script /coverage.sh --timeout 10 > ${SHARED_DIR}/replay.log 2>&1

# python3 ACE.py run_data $QUEUE_DIR > ${SHARED_DIR}/run_data.log


# # Generate and save the final .gcov files
# cd $COV_ROOT

# SRC_FILES=$(find . -type f \( -name "*.c" -o -name "*.cpp" -o -name "*.cc" -o -name "*.cxx" -o -name "*.h" -o -name "*.hpp" -o -name "*.hxx" \))

# for src in $SRC_FILES; do
#     echo "Checking coverage for $src"
#     # get the dir of the src file and the basename
#     src_dir=$(dirname "$src")
#     basename=$(basename "$src")
#     cd "$src_dir"

#     output=$(gcov -r -b -o . "$basename" 2>&1)

#     echo "$output"
    
#     # check if the file has coverage
#     if echo "$output" | grep "Lines executed:0.00%"; then
#         echo "No coverage, skipping: $src"
#         rm "$basename.gcov"
#     fi
    
#     cd $COV_ROOT
# done

# mkdir -p "$OUTPUT/gcov"
# find . -name "*.gcov" -type f -exec cp --parents {} "$OUTPUT/gcov/" \;

# echo "Coverage collection completed."
