FROM ubuntu:16.04
ENV DEBIAN_FRONTEND=noninteractive

# Install dependencies
RUN apt-get update && apt-get install -y \
        gcc-4.9 g++-4.9 \
        python2.7 python2.7-dev cmake git wget unzip \
        zlib1g-dev libcap-dev curl libtcmalloc-minimal4 \
        build-essential flex bison libgmp-dev libmpc-dev libmpfr-dev texinfo \
        libgoogle-perftools-dev libgtest-dev libsqlite3-dev libtinfo5 doxygen 

# Install LLVM 3.4
ENV LLVM_FILE=clang+llvm-3.4-x86_64-unknown-ubuntu12.04
RUN wget https://releases.llvm.org/3.4/${LLVM_FILE}.tar.xz
RUN tar -xf ${LLVM_FILE}.tar.xz
RUN mv ${LLVM_FILE} /opt/llvm-3.4
ENV PATH=/opt/llvm-3.4/bin:${PATH}
ENV LD_LIBRARY_PATH=/opt/llvm-3.4/lib:${LD_LIBRARY_PATH}
ENV LLVM_PATH=/opt/llvm-3.4/bin

# Install z3
RUN apt-get update && apt-get install -y python python-dev make
RUN git init z3
WORKDIR /z3
RUN git remote add origin https://github.com/Z3Prover/z3.git && \
    git fetch --depth 1 origin 4c664f1c05786a479e016ffac0d0c6a2e00ab64d && \
    git checkout FETCH_HEAD
RUN python scripts/mk_make.py && \
    cd build && \
    make -j$(nproc) && \
    make install

# Install KLEE-float
WORKDIR /
ENV CXXFLAGS="-D_GLIBCXX_USE_CXX11_ABI=0"
ENV KLEE_DIR=${PWD}/klee
RUN git clone -b tool_exchange_03.05.2017_rebase_extra_bug_fixes https://github.com/srg-imperial/klee-float.git klee
RUN apt-get update && apt-get install -y libtinfo-dev
RUN mkdir klee/build && cd klee/build && \
    cmake .. -DENABLE_SOLVER_STP=OFF -DENABLE_SOLVER_Z3=ON -DENABLE_POSIX_RUNTIME=ON -DENABLE_UNIT_TESTS=OFF -DENABLE_SYSTEM_TESTS=OFF \
             -DLLVM_CONFIG_BINARY=${LLVM_PATH}/llvm-config -DCMAKE_C_COMPILER=${LLVM_PATH}/clang -DCMAKE_CXX_COMPILER=${LLVM_PATH}/clang++ -DCMAKE_CXX_FLAGS="$CXXFLAGS" && \
    make -j$(nproc)

ENV PATH=/klee/build/bin/:${PATH}

# Install cmake 3.6
RUN curl -L https://cmake.org/files/v3.6/cmake-3.6.3.tar.gz -o cmake.tar.gz && \
    tar -xzf cmake.tar.gz && \
    cd cmake-3.6.3 && \
    ./bootstrap && \
    make -j"$(nproc)" && \
    make install && \
    cd .. && rm -rf cmake*

# Install python dependencies
RUN wget https://files.pythonhosted.org/packages/c5/cc/33162c0a7b28a4d8c83da07bc2b12cee58c120b4a9e8bba31c41c8d35a16/vcversioner-2.16.0.0.tar.gz && \
    wget https://files.pythonhosted.org/packages/c5/60/6ac26ad05857c601308d8fb9e87fa36d0ebf889423f47c3502ef034365db/functools32-3.2.3-2.tar.gz && \
    wget https://files.pythonhosted.org/packages/58/0d/c816f5ea5adaf1293a1d81d32e4cdfdaf8496973aa5049786d7fdb14e7e7/jsonschema-2.5.1.tar.gz && \
    wget https://files.pythonhosted.org/packages/4a/85/db5a2df477072b2902b0eb892feb37d88ac635d36245a72a6a69b23b383a/PyYAML-3.12.tar.gz
RUN ls -1 *.tar.gz | xargs -n1 tar -xzf && rm *.tar.gz
RUN apt-get install -y python-pip python-setuptools python-virtualenv
RUN cd vcversioner-2.16.0.0; python setup.py install
RUN cd functools32-3.2.3-2; python setup.py install
RUN cd jsonschema-2.5.1; python setup.py install
RUN cd PyYAML-3.12; python setup.py install

# Install wllvm
RUN wget https://files.pythonhosted.org/packages/16/47/1431ff16ec88c4e453697b3f6dd1b4bbb4c434e801e244696bee5b4ad501/wllvm-1.0.10.tar.gz
RUN tar -xzf wllvm-1.0.10.tar.gz && cd wllvm-1.0.10 && python setup.py install
ENV LLVM_COMPILER=clang

# Install tabulate for KLEE-stats
RUN cd ..; wget https://files.pythonhosted.org/packages/a7/81/8543858a091ec350f78431ba2865a4f36f5291fefa865930c044ebea6875/tabulate-0.8.0.tar.gz; \
    tar -xzf tabulate-0.8.0.tar.gz; rm tabulate-0.8.0.tar.gz; \
    cd tabulate-0.8.0; python setup.py install

# Create shared directory
RUN mkdir /shared