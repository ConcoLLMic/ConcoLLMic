FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive

# Install dependencies
RUN apt-get update && apt-get install -y \
    build-essential cmake curl file g++-multilib gcc-multilib git \
    libcap-dev libgoogle-perftools-dev libncurses5-dev libsqlite3-dev libtcmalloc-minimal4 \
    python3-pip python3-tabulate pipx unzip graphviz doxygen
RUN apt-get install -y clang-13 llvm-13 llvm-13-dev llvm-13-tools
RUN apt-get install -y \
    lcov bison flex libboost-all-dev perl zlib1g-dev minisat texinfo wget && \
    rm -rf /var/lib/apt/lists/*
RUN pip3 install lit wllvm tabulate gcovr b

RUN curl -OL https://github.com/google/googletest/archive/release-1.11.0.zip; unzip release-1.11.0.zip

RUN git clone https://github.com/stp/stp.git
RUN cd stp && git checkout tags/2.3.3
RUN mkdir stp/build && cd stp/build && \
    cmake .. && make && make install

RUN git clone https://github.com/klee/klee-uclibc.git
RUN cd klee-uclibc && \
    ./configure --make-llvm-lib --with-cc clang-13 --with-llvm-config /usr/bin/llvm-config-13 && \
    make -j2

# Install KLEE
RUN git clone https://github.com/klee/klee.git
RUN cd klee && git checkout 1a70516
RUN mkdir klee/build && cd klee/build && \
    cmake .. -DENABLE_SOLVER_STP=ON -DENABLE_POSIX_RUNTIME=ON -DENABLE_UNIT_TESTS=OFF -DENABLE_SYSTEM_TESTS=OFF \
             -DLLVM_CONFIG_BINARY=/usr/bin/llvm-config-13 -DKLEE_UCLIBC_PATH=/klee-uclibc && \
    make

ENV PATH=/klee/build/bin/:${PATH}

ENV LLVM_COMPILER="clang"
RUN ln -sf $(which clang-13) /usr/local/bin/clang
RUN ln -sf $(which clang++-13) /usr/local/bin/clang++
RUN ln -sf $(which llvm-ar-13) /usr/local/bin/llvm-ar
RUN ln -sf $(which llvm-link-13) /usr/local/bin/llvm-link

# Create shared directory
RUN mkdir /shared