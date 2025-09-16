FROM ubuntu:noble

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=Etc/UTC

RUN apt-get update
RUN apt-get install -y cmake llvm-14 clang-14 libc++-14-dev libc++abi-14-dev libunwind-14-dev \
    python3-minimal python-is-python3 zlib1g-dev git joe libprotobuf-dev libboost-all-dev

WORKDIR /workdir
RUN git clone https://github.com/R-Fuzz/symsan.git /workdir/symsan && cd /workdir/symsan && git reset --hard v1.1.0

RUN git clone --depth=1 https://github.com/AFLplusplus/AFLplusplus /workdir/aflpp
ENV LLVM_CONFIG=llvm-config-14
RUN cd /workdir/aflpp && CC=clang-14 CXX=clang++-14 make install

RUN apt-get install -y libz3-dev libgoogle-perftools-dev wget git \
    python3-pip \
    lcov \
    wget \
    curl \
    autoconf \
    make \
    build-essential \
    libtool \
    pkg-config

RUN python3 -m pip install gcovr==6.0 --break-system-packages

RUN cd symsan/ && mkdir -p build && \
    cd build && CC=clang-14 CXX=clang++-14 cmake -DCMAKE_INSTALL_PREFIX=. -DAFLPP_PATH=/workdir/aflpp ../  && \
    make -j4 && make install

COPY symsan_pure_concolic_execution.sh /workdir/symsan_pure_concolic_execution.sh
RUN chmod +x /workdir/symsan_pure_concolic_execution.sh

ENV KO_CC=clang-14
ENV KO_CXX=clang++-14
ENV KO_USE_FASTGEN=1